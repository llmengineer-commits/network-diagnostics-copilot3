"""Tests for ingest.py's chunking logic — the vendor-tagging bug found
during manual testing is pinned down here so it can't regress."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingest import chunk_document, load_documents


def test_load_documents_tags_vendor_from_subfolder():
    docs = load_documents()
    by_source = {d["source"]: d for d in docs}
    assert any(d["vendor"] == "mikrotik" for d in docs)
    assert any(d["vendor"] == "huawei" for d in docs)
    assert any(d["vendor"] == "general" for d in docs)
    for source, doc in by_source.items():
        assert source.startswith(doc["vendor"]) or doc["vendor"] == "general"


def test_chunk_heading_reflects_actual_section_not_doc_title():
    """
    Regression test for a real bug found during development: a short
    intro block merging forward into the next section was picking up
    the DOC TITLE as its heading instead of the section it actually
    contains, which would have broken retrieval citations.
    """
    doc = {
        "source": "test.md",
        "vendor": "general",
        "text": (
            "# Doc Title\n\n"
            "> a short intro line\n\n"
            "## Real Section Heading\n\n"
            "Enough body text here to make this section clearly the "
            "longest part of the merged chunk, well past the minimum "
            "chunk size threshold so it does not get merged forward "
            "into whatever chunk follows it in the document. Padding "
            "padding padding padding padding padding padding padding."
        ),
    }
    chunks = chunk_document(doc, min_chunk_chars=200)
    assert len(chunks) == 1
    assert chunks[0]["heading"] == "Real Section Heading"


def test_chunk_document_produces_nonempty_chunks():
    docs = load_documents()
    for doc in docs:
        chunks = chunk_document(doc)
        assert len(chunks) > 0
        for c in chunks:
            assert c["text"].strip()
            assert c["vendor"] == doc["vendor"]
            assert c["id"].startswith(doc["source"])
