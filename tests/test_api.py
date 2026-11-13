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
