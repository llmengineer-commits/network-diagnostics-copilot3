"""
Ingestion pipeline: raw vendor documentation -> chunked, embedded, indexed
vector store.

Design choices (documented per the project rubric's reproducibility
requirement):

- Embeddings: local sentence-transformers model (all-MiniLM-L6-v2) by
  default. No API key required, runs fine on 8GB RAM, and keeps ingestion
  reproducible offline once the model is cached. Swap EMBEDDING_PROVIDER
  to "openai" in .env if you'd rather use a hosted embedding API.
- Vector store: Qdrant in embedded/local mode (on-disk, no server or
  Docker required). This is the same client library used against a real
  Qdrant Cloud deployment, so moving to a hosted instance later is a
  one-line config change (see QDRANT_URL in .env.example).
- Chunking: simple heading-aware splitting. The sample docs are
  structured with clear ## sections, so splitting on headings keeps each
  chunk topically coherent, which matters more for retrieval quality here
  than a fixed token-count splitter would.

Run:
    python ingest.py
"""

import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DOCS_DIR = Path(__file__).parent / "data" / "docs"
QDRANT_PATH = Path(__file__).parent / "qdrant_data"
COLLECTION_NAME = "network_docs"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")


def load_documents():
    """
    Read every markdown file under data/docs/, recursively. The
    immediate subfolder name is treated as the vendor tag (e.g.
    data/docs/mikrotik/*.md -> vendor='mikrotik'), so retrieval can be
    filtered or reported by manufacturer. Files directly under
    data/docs/ (not in a vendor subfolder) get vendor='general'.
    """
    docs = []
    for path in sorted(DOCS_DIR.rglob("*.md")):
        rel = path.relative_to(DOCS_DIR)
        vendor = rel.parts[0] if len(rel.parts) > 1 else "general"
        text = path.read_text(encoding="utf-8")
        docs.append({"source": str(rel), "vendor": vendor, "text": text})
    return docs


def chunk_document(doc, min_chunk_chars=200):
    """
    Split on markdown headings (## and ###) so each chunk is one
    topically coherent section rather than an arbitrary token window.
    Small trailing fragments get merged into the previous chunk.
    """
    text = doc["text"]
    # split, keeping the heading with the section that follows it
    pieces = re.split(r"\n(?=#{1,3} )", text)
    chunks = []
    buffer = ""
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if len(buffer) and len(buffer) < min_chunk_chars:
            buffer += "\n\n" + piece
        else:
            if buffer:
                chunks.append(buffer)
            buffer = piece
    if buffer:
        chunks.append(buffer)

    heading_re = re.compile(r"^#{1,3}\s*(.+)$", re.MULTILINE)
    out = []
    for i, chunk_text in enumerate(chunks):
        # a short intro block can get merged forward into the next
        # section (see min_chunk_chars above), which means the FIRST
        # heading in the merged text is the doc title, not the section
        # the chunk is actually about. Use the LAST heading match so
        # metadata reflects the most specific (deepest) section present.
        matches = list(heading_re.finditer(chunk_text))
        heading = matches[-1].group(1).strip() if matches else doc["source"]
        out.append(
            {
                "id": f"{doc['source']}::chunk{i}",
                "source": doc["source"],
                "vendor": doc["vendor"],
                "heading": heading,
                "text": chunk_text,
            }
        )
    return out


def build_index():
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams
    from sentence_transformers import SentenceTransformer

    print(f"Loading documents from {DOCS_DIR} ...")
    docs = load_documents()
    if not docs:
        raise SystemExit(f"No .md files found in {DOCS_DIR}")
    print(f"  found {len(docs)} document(s)")

    all_chunks = []
    for doc in docs:
        chunks = chunk_document(doc)
        print(f"  {doc['source']}: {len(chunks)} chunk(s)")
        all_chunks.extend(chunks)

    print(f"\nLoading embedding model '{EMBEDDING_MODEL}' ...")
    model = SentenceTransformer(EMBEDDING_MODEL)
    vector_size = model.get_sentence_embedding_dimension()

    print(f"Embedding {len(all_chunks)} chunks ...")
    texts = [c["text"] for c in all_chunks]
    vectors = model.encode(texts, show_progress_bar=True)

    print(f"\nWriting to local Qdrant store at {QDRANT_PATH} ...")
    client = QdrantClient(path=str(QDRANT_PATH))

    if client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )

    points = [
        PointStruct(
            id=i,
            vector=vectors[i].tolist(),
            payload={
                "chunk_id": chunk["id"],
                "source": chunk["source"],
                "vendor": chunk["vendor"],
                "heading": chunk["heading"],
                "text": chunk["text"],
            },
        )
        for i, chunk in enumerate(all_chunks)
    ]
    client.upsert(collection_name=COLLECTION_NAME, points=points)

    print(f"\nDone. Indexed {len(points)} chunks into collection '{COLLECTION_NAME}'.")
    return len(points)


if __name__ == "__main__":
    build_index()
