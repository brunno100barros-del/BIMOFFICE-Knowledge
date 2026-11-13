"""Testes da camada HTTP (FastAPI) com TestClient — dados isolados em pasta temporária."""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from tests.conftest import make_docx

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _upload(client, tmp_path, name="a.docx", styled=True, **meta):
    f = make_docx(tmp_path / name, styled)
    with open(f, "rb") as fh:
        return client.post("/api/library/documents",
                           files={"file": (name, fh, DOCX_MIME)}, data=meta), f


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_full_document_lifecycle(client, tmp_path):
    r, src = _upload(client, tmp_path, title="Reforma X", unit="Porto Velho",
                     discipline="Arquitetura", tags="piso, pintura")
    assert r.status_code == 201, r.text
    doc = r.json()
    did = doc["id"]
    assert doc["title"] == "Reforma X" and doc["tags"] == ["pintura", "piso"]

    assert [d["id"] for d in client.get("/api/library/documents").json()] == [did]
    assert client.get("/api/library/documents", params={"unit": "Outra"}).json() == []
    assert client.get(f"/api/library/documents/{did}").json()["id"] == did
    assert len(client.get(f"/api/library/documents/{did}/sections").json()) == 3
    chunks = client.get(f"/api/library/documents/{did}/chunks").json()
    assert len(chunks) == doc["n_chunks"]

    r = client.patch(f"/api/library/documents/{did}", json={"project": "Bloco A"})
    assert r.status_code == 200 and r.json()["project"] == "Bloco A"

    r = client.get(f"/api/library/documents/{did}/original")
    assert r.status_code == 200 and r.content == src.read_bytes()

    hits = client.get("/api/library/search-text", params={"q": "ceramico sanitarios"}).json()
    assert hits and hits[0]["document_id"] == did

    assert client.post(f"/api/library/documents/{did}/reindex").status_code == 200

    assert client.delete(f"/api/library/documents/{did}").status_code == 204
    assert client.get("/api/library/documents").json() == []
    assert len(client.get("/api/library/documents",
                          params={"include_deleted": True}).json()) == 1
    r = client.post(f"/api/library/documents/{did}/restore")
    assert r.status_code == 200 and r.json()["deleted_at"] is None

    r = client.post("/api/library/backup")
    assert r.status_code == 200 and r.json()["backup"]


def test_duplicate_returns_409(client, tmp_path):
    assert _upload(client, tmp_path)[0].status_code == 201
    assert _upload(client, tmp_path)[0].status_code == 409


def test_invalid_file_returns_400(client):
    r = client.post("/api/library/documents",
                    files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 400


def test_not_found_returns_404(client):
    for url in ("/api/library/documents/999", "/api/library/documents/999/sections",
                "/api/library/documents/999/chunks", "/api/library/documents/999/original"):
        assert client.get(url).status_code == 404, url
    assert client.post("/api/library/documents/999/reindex").status_code == 404
    assert client.delete("/api/library/documents/999").status_code == 404


def test_patch_validates_body(client, tmp_path):
    did = _upload(client, tmp_path)[0].json()["id"]
    assert client.patch(f"/api/library/documents/{did}", json={"title": 123}).status_code == 422
    # campos internos (hash, id) não podem ser alterados
    assert client.patch(f"/api/library/documents/{did}", json={"sha256": "x"}).status_code == 422
    r = client.patch(f"/api/library/documents/{did}", json={"tags": ["b", "a"]})
    assert r.status_code == 200 and r.json()["tags"] == ["a", "b"]
    assert client.patch("/api/library/documents/999", json={"title": "x"}).status_code == 404


# ------------------------------------------------------------------ evolução: PDF, painel, acesso web
def test_pdf_upload_stats_and_inline_original(client, tmp_path):
    from tests.conftest import PDF_PAGES, make_pdf
    f = make_pdf(tmp_path / "m.pdf", PDF_PAGES)
    r = client.post("/api/library/documents",
                    files={"file": ("m.pdf", f.read_bytes(), "application/pdf")})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    assert r.json()["file_type"] == "pdf"
    _upload(client, tmp_path)  # + 1 DOCX
    st = client.get("/api/library/stats").json()
    assert (st["documents_total"], st["documents_docx"], st["documents_pdf"]) == (2, 1, 1)
    assert len(st["recent"]) == 2
    r = client.get(f"/api/library/documents/{did}/original", params={"inline": True})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline")
    assert r.content == f.read_bytes()
    pdfs = client.get("/api/library/documents", params={"file_type": "pdf"}).json()
    assert [d["id"] for d in pdfs] == [did]


def test_scanned_pdf_returns_clear_400(client, tmp_path):
    from tests.conftest import make_pdf
    f = make_pdf(tmp_path / "scan.pdf", [[]])
    r = client.post("/api/library/documents", files={"file": ("scan.pdf", f.read_bytes())})
    assert r.status_code == 400 and "texto extraível" in r.json()["detail"]


def test_config_endpoint(client):
    c = client.get("/api/config").json()
    assert ".pdf" in c["allowed_extensions"] and c["auth_required"] is False
    assert c["gdrive"]["available"] is False


def test_api_token_protects_api(client, monkeypatch):
    from backend import config
    monkeypatch.setattr(config, "API_TOKEN", "segredo-123")
    assert client.get("/api/health").status_code == 200          # público
    assert client.get("/api/config").json()["auth_required"] is True
    assert client.get("/api/library/documents").status_code == 401
    bad = {"Authorization": "Bearer errado"}
    assert client.get("/api/library/documents", headers=bad).status_code == 401
    ok = {"Authorization": "Bearer segredo-123"}
    assert client.get("/api/library/documents", headers=ok).status_code == 200


def test_cors_allows_github_pages_and_private_network(client):
    origin = "https://brunno100barros-del.github.io"
    r = client.options("/api/library/stats", headers={
        "Origin": origin, "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
        "Access-Control-Request-Private-Network": "true"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == origin
    assert r.headers["access-control-allow-private-network"] == "true"
    r = client.get("/api/health", headers={"Origin": "https://site-estranho.example"})
    assert "access-control-allow-origin" not in r.headers
