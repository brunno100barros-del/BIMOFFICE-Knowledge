"""Login, permissões por projeto e auditoria (BIMOFFICE_AUTH=on)."""
import pytest
from fastapi.testclient import TestClient

from backend import auth, config, jobs
from backend.database.db import get_conn
from backend.main import app
from tests.conftest import make_docx

pytest.importorskip("ifcopenshell")
from tests.ifc_factory import build_model  # noqa: E402


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(config, "AUTH", "on")
    auth.create_user("admin@senai.br", "Admin", "senha-admin-123", "admin")
    auth.create_user("ana@senai.br", "Ana", "senha-ana-1234", "editor")
    auth.create_user("bruno@senai.br", "Bruno", "senha-bruno-123", "editor")
    auth.create_user("leo@senai.br", "Léo", "senha-leo-12345", "leitor")
    with TestClient(app) as client:
        yield client


def login(c, email, pw):
    r = c.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_login_required_and_wrong_password(c):
    assert c.get("/api/health").status_code == 200            # público
    assert c.get("/api/config").json()["auth_mode"] == "on"
    assert c.get("/api/projects").status_code == 401
    assert c.get("/api/library/documents").status_code == 401
    assert c.post("/api/auth/login", json={"email": "ana@senai.br", "password": "errada"}).status_code == 401
    h = login(c, "ANA@senai.br", "senha-ana-1234")             # e-mail sem diferenciar maiúsculas
    assert c.get("/api/auth/me", headers=h).json()["email"] == "ana@senai.br"
    c.post("/api/auth/logout", headers=h)
    assert c.get("/api/auth/me", headers=h).status_code == 401  # sessão encerrada


def test_passwords_and_tokens_are_never_stored_in_clear(c):
    tok = c.post("/api/auth/login", json={"email": "ana@senai.br", "password": "senha-ana-1234"}).json()["token"]
    with get_conn() as conn:
        dump = " ".join(str(tuple(r)) for t in ("users", "sessions") for r in conn.execute(f"SELECT * FROM {t}"))
    assert "senha-ana-1234" not in dump and tok not in dump
    assert "password_hash" not in str(c.get("/api/users", headers=login(c, "admin@senai.br", "senha-admin-123")).json())


def test_project_isolation_between_teams(c, tmp_path):
    ana, bruno = login(c, "ana@senai.br", "senha-ana-1234"), login(c, "bruno@senai.br", "senha-bruno-123")
    pid = c.post("/api/projects", json={"name": "Projeto da Ana"}, headers=ana).json()["id"]
    ifc = build_model(tmp_path / "m.ifc", "IFC4")
    assert c.post(f"/api/projects/{pid}/files", files={"file": ("m.ifc", ifc.read_bytes())}, headers=ana).status_code == 201
    jobs.run_pending()
    mid = c.get(f"/api/projects/{pid}/ifc-models", headers=ana).json()[0]["id"]
    eid = c.get(f"/api/ifc-models/{mid}/elements", headers=ana).json()["items"][0]["id"]
    mem = c.post(f"/api/projects/{pid}/memorials", json={}, headers=ana).json()
    # Bruno não vê nada do projeto da Ana — por nenhuma rota
    assert c.get("/api/projects", headers=bruno).json() == []
    assert c.get("/api/memorials", headers=bruno).json() == []
    for url in (f"/api/projects/{pid}", f"/api/projects/{pid}/files", f"/api/ifc-models/{mid}",
                f"/api/ifc-models/{mid}/elements", f"/api/ifc-models/{mid}/export", f"/api/ifc-elements/{eid}",
                f"/api/memorials/{mem['id']}", f"/api/memorials/{mem['id']}/export",
                f"/api/memorial-chapters/{mem['chapters'][0]['id']}/history", f"/api/jobs?project_id={pid}"):
        assert c.get(url, headers=bruno).status_code == 403, url
    assert c.patch(f"/api/memorial-chapters/{mem['chapters'][0]['id']}", json={"text": "x"}, headers=bruno).status_code == 403
    assert c.get("/api/jobs", headers=bruno).status_code == 403
    # Ana adiciona Léo como leitor: ele vê, mas não altera
    assert c.post(f"/api/projects/{pid}/members", json={"email": "leo@senai.br", "role": "leitor"}, headers=ana).status_code == 200
    leo = login(c, "leo@senai.br", "senha-leo-12345")
    assert [p["id"] for p in c.get("/api/projects", headers=leo).json()] == [pid]
    assert c.get(f"/api/memorials/{mem['id']}", headers=leo).status_code == 200
    assert c.patch(f"/api/memorial-chapters/{mem['chapters'][0]['id']}", json={"text": "x"}, headers=leo).status_code == 403
    assert c.post(f"/api/projects/{pid}/files", files={"file": ("a.pdf", b"%PDF-1.4")}, headers=leo).status_code == 403
    assert c.post(f"/api/projects/{pid}/members", json={"email": "bruno@senai.br"}, headers=leo).status_code == 403
    assert c.delete(f"/api/projects/{pid}", headers=leo).status_code == 403
    # o administrador vê tudo
    adm = login(c, "admin@senai.br", "senha-admin-123")
    assert [p["id"] for p in c.get("/api/projects", headers=adm).json()] == [pid]
    # o projeto não pode ficar sem dono
    ana_id = next(m["user_id"] for m in c.get(f"/api/projects/{pid}/members", headers=ana).json() if m["role"] == "dono")
    assert c.delete(f"/api/projects/{pid}/members/{ana_id}", headers=ana).status_code == 400


def test_library_roles(c, tmp_path):
    leo, ana = login(c, "leo@senai.br", "senha-leo-12345"), login(c, "ana@senai.br", "senha-ana-1234")
    data = make_docx(tmp_path / "a.docx").read_bytes()
    assert c.post("/api/library/documents", files={"file": ("a.docx", data)}, headers=leo).status_code == 403
    assert c.post("/api/library/documents", files={"file": ("a.docx", data)}, headers=ana).status_code == 201
    assert len(c.get("/api/library/documents", headers=leo).json()) == 1      # leitor consulta a biblioteca
    assert c.get("/api/search", params={"q": "revestimento"}, headers=leo).status_code == 200
    assert c.post("/api/projects", json={"name": "x"}, headers=leo).status_code == 403
    assert c.get("/api/users", headers=ana).status_code == 403
    assert c.get("/api/audit", headers=ana).status_code == 403


def test_admin_manages_users_and_deactivation_kicks_out(c):
    adm = login(c, "admin@senai.br", "senha-admin-123")
    r = c.post("/api/users", json={"email": "novo@senai.br", "name": "Novo", "password": "curta", "role": "editor"}, headers=adm)
    assert r.status_code == 400                                               # senha fraca
    uid = c.post("/api/users", json={"email": "novo@senai.br", "name": "Novo", "password": "senha-longa-1",
                                     "role": "editor"}, headers=adm).json()["id"]
    h = login(c, "novo@senai.br", "senha-longa-1")
    assert c.get("/api/auth/me", headers=h).status_code == 200
    c.patch(f"/api/users/{uid}", json={"active": False}, headers=adm)
    assert c.get("/api/auth/me", headers=h).status_code == 401              # sessão derrubada
    assert c.post("/api/auth/login", json={"email": "novo@senai.br", "password": "senha-longa-1"}).status_code == 401


def test_audit_log_records_changes_and_logins(c):
    ana = login(c, "ana@senai.br", "senha-ana-1234")
    c.post("/api/auth/login", json={"email": "ana@senai.br", "password": "errada"})
    c.post("/api/projects", json={"name": "Auditado"}, headers=ana)
    log = c.get("/api/audit", headers=login(c, "admin@senai.br", "senha-admin-123")).json()
    actions = [(x["email"], x["action"], x["status"]) for x in log]
    assert ("ana@senai.br", "POST /api/projects", 201) in actions
    assert ("ana@senai.br", "login recusado", 401) in actions
    assert ("ana@senai.br", "login", 200) in actions


def test_session_expiry(c):
    h = login(c, "ana@senai.br", "senha-ana-1234")
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET expires_at='2000-01-01 00:00:00'")
    assert c.get("/api/auth/me", headers=h).status_code == 401


def test_admin_bootstrap_from_env(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_EMAIL", "chefe@senai.br")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "senha-inicial-9")
    auth.ensure_admin_from_env()
    auth.ensure_admin_from_env()                                              # idempotente
    assert [u["email"] for u in auth.list_users()] == ["chefe@senai.br"]
