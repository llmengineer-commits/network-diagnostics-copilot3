"""
Retrieval tool: semantic search over the vendor documentation indexed by
ingest.py. Kept separate from tools.py because this one loads a model and
opens the local Qdrant store on import, whereas the router tools are
lightweight HTTP calls.
"""

import os
from pathlib import Path

from langchain_core.tools import tool

QDRANT_PATH = Path(__file__).parent.parent / "qdrant_data"
COLLECTION_NAME = "network_docs"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "4"))

_model = None
_client = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _get_client():
    global _client
    if _client is None:
        from qdrant_client import QdrantClient

        if not QDRANT_PATH.exists():
            raise RuntimeError(
                f"No vector store found at {QDRANT_PATH}. Run `python ingest.py` first."
            )
        _client = QdrantClient(path=str(QDRANT_PATH))
    return _client


def search_docs(query: str, top_k: int = TOP_K, vendor: str | None = None) -> list[dict]:
    """
    Run a semantic search against the indexed vendor docs. If `vendor`
    is given (e.g. 'mikrotik', 'huawei'), results are filtered to that
    manufacturer's docs; otherwise search spans all vendors.
    """
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    model = _get_model()
    client = _get_client()
    query_vector = model.encode(query).tolist()
    query_filter = None
    if vendor:
        query_filter = Filter(must=[FieldCondition(key="vendor", match=MatchValue(value=vendor))])
    hits = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
        query_filter=query_filter,
    ).points
    return [
        {
            "score": hit.score,
            "source": hit.payload["source"],
            "vendor": hit.payload.get("vendor", "general"),
            "heading": hit.payload["heading"],
            "text": hit.payload["text"],
        }
        for hit in hits
    ]


@tool
def search_vendor_docs(query: str, vendor: str = "") -> str:
    """
    Search the vendor documentation for guidance relevant to a
    networking symptom or question, e.g. 'PPPoE session keeps dropping'
    or 'DHCP lease expired but client still connected'. Optionally pass
    vendor ('mikrotik' or 'huawei') to restrict the search to that
    manufacturer's documentation if the technician has said which
    hardware is involved; leave it empty to search all vendors. Returns
    the most relevant documentation sections with their source, vendor,
    and heading, so answers can be grounded and cited.
    """
    hits = search_docs(query, vendor=vendor or None)
    if not hits:
        scope = f" for vendor '{vendor}'" if vendor else ""
        return f"No relevant documentation found{scope}."
    formatted = []
    for h in hits:
        formatted.append(
            f"[{h['vendor']}/{h['source']} — {h['heading']} (relevance: {h['score']:.2f})]\n{h['text']}"
        )
    return "\n\n---\n\n".join(formatted)
