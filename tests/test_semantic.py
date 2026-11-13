"""Mecânica da pesquisa híbrida (com provedor de teste; sem baixar modelo)."""
import pytest
from fastapi.testclient import TestClient

from backend.database.db import get_conn
from backend.main import app
from backend.semantic_search import hybrid, providers, vector_store
from backend.semantic_search.providers import EmbeddingUnavailable
from backend.services import library_service as svc
from tests.conftest import make_docx


def _imp(tmp_path, name, styled=True, **meta):
    f = make_docx(tmp_path / name, styled)
    doc = svc.import_document(name, f.read_bytes(), meta)
    vector_store.index_pending(doc["id"])
    return doc


def test_vectors_are_stored_and_counted(tmp_path):
    _imp(tmp_path, "a.docx")
    st = vector_store.status("fake-test-provider")
    assert st["chunks_total"] > 0 and st["chunks_pending"] == 0
    with get_conn() as conn:
        r = conn.execute("SELECT embedding, embedding_model FROM chunks LIMIT 1").fetchone()
    assert len(r["embedding"]) == 256 * 4 and r["embedding_model"] == "fake-test-provider"


def test_hybrid_returns_source_and_relative_relevance(tmp_path):
    _imp(tmp_path, "a.docx", unit="Porto Velho", discipline="Arquitetura", project="Bloco A")
    res = hybrid.search("revestimento cerâmico sanitários")
    assert res["semantic_used"] and res["results"]
    top = res["results"][0]
    assert top["relative_relevance"] == 100
    assert set(top["found_by"]) == {"semântica", "textual"}
    assert top["document_title"] == "a" and top["unit"] == "Porto Velho"
    assert "Revestimentos" in top["section_path"]
    assert all(0 <= r["relative_relevance"] <= 100 for r in res["results"])


def test_filters_apply_to_both_searches(tmp_path):
    _imp(tmp_path, "a.docx", unit="Porto Velho", discipline="Arquitetura", project="Bloco A")
    _imp(tmp_path, "b.docx", styled=False, unit="Ji-Paraná", discipline="Cobertura")
    for kw in ({"unit": "Ji-Paraná"}, {"discipline": "Cobertura"}):
        res = hybrid.search("paredes telha", **kw)
        assert res["results"] and all(r["document_title"] == "b" for r in res["results"])
    res = hybrid.search("paredes telha", project="Bloco A")
    assert res["results"] and all(r["document_title"] == "a" for r in res["results"])


def test_deleted_documents_are_not_returned(tmp_path):
    a = _imp(tmp_path, "a.docx")
    svc.delete_document(a["id"])
    assert hybrid.search("revestimento cerâmico")["results"] == []


def test_reindex_document_clears_vectors_until_regenerated(tmp_path):
    a = _imp(tmp_path, "a.docx")
    svc.reindex_document(a["id"])
    assert vector_store.status("fake-test-provider")["chunks_pending"] > 0
    vector_store.index_pending()
    assert vector_store.status("fake-test-provider")["chunks_pending"] == 0


def test_pending_chunks_produce_warning(tmp_path):
    f = make_docx(tmp_path / "a.docx")
    svc.import_document("a.docx", f.read_bytes(), {})  # sem gerar vetores
    res = hybrid.search("revestimento")
    assert any("sem vetor" in w for w in res["warnings"])


class _Broken:
    name = "quebrado"

    def embed_query(self, t):
        raise EmbeddingUnavailable("modelo ausente")

    def embed_passages(self, t):
        raise EmbeddingUnavailable("modelo ausente")


def test_without_model_falls_back_to_text_with_explicit_warning(tmp_path):
    f = make_docx(tmp_path / "a.docx")
    svc.import_document("a.docx", f.read_bytes(), {})
    providers.set_provider(_Broken())
    res = hybrid.search("revestimento cerâmico")
    assert not res["semantic_used"]
    assert any("INDISPONÍVEL" in w for w in res["warnings"])
    assert res["results"] and all(r["found_by"] == ["textual"] for r in res["results"])
    assert hybrid.search("revestimento", mode="semantic")["results"] == []


def test_invalid_mode():
    with pytest.raises(ValueError):
        hybrid.search("x", mode="aleatorio")


# ------------------------------------------------------------------ HTTP
def test_search_routes(tmp_path):
    with TestClient(app) as c:
        f = make_docx(tmp_path / "a.docx")
        r = c.post("/api/library/documents", files={"file": ("a.docx", f.read_bytes())},
                   data={"unit": "Porto Velho"})
        assert r.status_code == 201
        st = c.get("/api/search/status").json()
        assert st["chunks_pending"] == 0  # vetores gerados na importação
        r = c.get("/api/search", params={"q": "pintura acrílica", "unit": "Porto Velho"})
        assert r.status_code == 200 and r.json()["results"]
        assert c.get("/api/search", params={"q": "x", "mode": "zzz"}).status_code == 400
        r = c.post("/api/search/reindex", params={"force": True})
        assert r.status_code == 200 and r.json()["indexed"] == st["chunks_total"]
        providers.set_provider(_Broken())
        assert c.post("/api/search/reindex", params={"force": True}).status_code == 503
        # importar continua funcionando mesmo sem modelo
        g = make_docx(tmp_path / "b.docx", styled=False)
        assert c.post("/api/library/documents",
                      files={"file": ("b.docx", g.read_bytes())}).status_code == 201
