import numpy as np
import pytest

from app.rag.ingestion import IngestionError, build_chunks, infer_category
from app.rag.retriever import lexical_coverage, mmr_select
from tests.conftest import KB


def test_pdf_and_txt_ingestion_with_metadata():
    txt = build_chunks(KB / "vpn_troubleshooting.txt")
    pdf = build_chunks(KB / "email_and_outlook_guide.pdf")
    assert txt[0]["metadata"]["category"] == "network"
    assert txt[0]["metadata"]["doc_type"] == "txt"
    assert pdf[0]["metadata"]["doc_type"] == "pdf" and pdf[0]["metadata"]["page"] == 1


def test_unsupported_file(tmp_path):
    f = tmp_path / "x.exe"
    f.write_text("hi")
    with pytest.raises(IngestionError):
        build_chunks(f)


def test_category_inference():
    assert infer_category("my password is locked") == "account"
    assert infer_category("nothing relevant here") == "general"


def test_similarity_search_returns_citations(retriever):
    res = retriever.search("VPN will not connect", strategy="similarity")
    assert res and res[0]["source"] == "vpn_troubleshooting.txt"
    assert res[0]["citation"].startswith("[1] vpn_troubleshooting.txt")


def test_metadata_filter(retriever):
    res = retriever.search("device problem", category="security")
    assert res and all(r["category"] == "security" for r in res)


def test_mmr_and_rerank_order(retriever):
    res = retriever.search("password locked account", k=3, strategy="mmr", rerank=True)
    scores = [r["score"] for r in res]
    assert scores == sorted(scores, reverse=True)
    assert res[0]["category"] == "account"


def test_mmr_prefers_diverse_results():
    q = np.array([1.0, 0.0])
    docs = np.array([[1.0, 0.0], [0.999, 0.045], [0.6, 0.8]])
    docs = docs / np.linalg.norm(docs, axis=1, keepdims=True)
    assert mmr_select(q, docs, k=2, lam=0.3) == [0, 2]  # skips the near-duplicate


def test_lexical_coverage():
    assert lexical_coverage("vpn connect", "the vpn will connect") == 1.0
    assert lexical_coverage("vpn connect", "printer") == 0.0
