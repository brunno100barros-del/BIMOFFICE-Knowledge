"""Login, sessões, permissões por projeto e auditoria.

Modos (BIMOFFICE_AUTH):
- off (padrão): uso local no próprio computador — tudo liberado, como nas versões anteriores.
- on (nuvem): login obrigatório; cada usuário vê só os projetos da sua equipe.

Papéis globais: admin (tudo) · editor (importa na biblioteca, cria projetos) · leitor (só consulta).
Papéis no projeto: dono (gerencia equipe) · editor (altera) · leitor (consulta).
Senhas: só o hash scrypt (biblioteca padrão do Python) é guardado. Tokens de sessão: só o hash SHA-256.
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from backend import config
from backend.database.db import get_conn

log = logging.getLogger("bimoffice.auth")
ROLES = ("admin", "editor", "leitor")
PROJECT_ROLES = ("dono", "editor", "leitor")
LOCAL_USER = {"id": 0, "email": "local", "name": "Uso local", "role": "admin", "active": 1, "local": True}
current_user: contextvars.ContextVar[dict | None] = contextvars.ContextVar("current_user", default=None)


class AuthError(Exception):
    pass


class Forbidden(AuthError):
    pass


def enabled() -> bool:
    return config.AUTH == "on"


def user() -> dict:
    """Usuário da requisição atual (no modo local, um administrador local)."""
    return current_user.get() or (LOCAL_USER if not enabled() else {})


def _now(delta_hours: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=delta_hours)).strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------ senhas
def hash_password(pw: str) -> str:
    if len(pw or "") < 8:
        raise AuthError("A senha precisa ter pelo menos 8 caracteres.")
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt((pw or "").encode(), salt=base64.b64decode(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


# ------------------------------------------------------------------ usuários
def _public(r) -> dict:
    d = dict(r)
    d.pop("password_hash", None)
    return d


def create_user(email: str, name: str, password: str, role: str = "leitor") -> dict:
    email = (email or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise AuthError("E-mail inválido.")
    if role not in ROLES:
        raise AuthError(f"Papel inválido. Use: {', '.join(ROLES)}.")
    ph = hash_password(password)
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise AuthError("Já existe um usuário com este e-mail.")
        uid = conn.execute("INSERT INTO users(email, name, password_hash, role) VALUES (?,?,?,?)",
                           (email, (name or "").strip(), ph, role)).lastrowid
    return get_user(uid)


def get_user(uid: int) -> dict:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not r:
        raise AuthError("Usuário não encontrado.")
    return _public(r)


def list_users() -> list[dict]:
    with get_conn() as conn:
        return [_public(r) for r in conn.execute("SELECT * FROM users ORDER BY email")]


def update_user(uid: int, fields: dict) -> dict:
    get_user(uid)
    sets, vals = [], []
    if fields.get("name") is not None:
        sets.append("name=?"); vals.append(fields["name"].strip())
    if fields.get("role") is not None:
        if fields["role"] not in ROLES:
            raise AuthError("Papel inválido.")
        sets.append("role=?"); vals.append(fields["role"])
    if fields.get("active") is not None:
        sets.append("active=?"); vals.append(1 if fields["active"] else 0)
    if fields.get("password"):
        sets.append("password_hash=?"); vals.append(hash_password(fields["password"]))
    if sets:
        with get_conn() as conn:
            conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", (*vals, uid))
            if fields.get("active") is False or fields.get("password"):
                conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))  # derruba sessões abertas
    return get_user(uid)


def ensure_admin_from_env() -> None:
    """Na 1ª implantação: cria o administrador definido nas variáveis de ambiente (se não houver usuários)."""
    if not (config.ADMIN_EMAIL and config.ADMIN_PASSWORD):
        return
    with get_conn() as conn:
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return
    create_user(config.ADMIN_EMAIL, "Administrador", config.ADMIN_PASSWORD, "admin")
    log.info("Administrador inicial criado: %s", config.ADMIN_EMAIL)


# ------------------------------------------------------------------ sessões
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def login(email: str, password: str, ip: str = "") -> dict:
    email = (email or "").strip().lower()
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    ok = bool(r) and r["active"] and verify_password(password, r["password_hash"])
    audit(r["id"] if r else None, email, "login" if ok else "login recusado", 200 if ok else 401, ip)
    if not ok:
        raise AuthError("E-mail ou senha incorretos (ou usuário desativado).")
    token = secrets.token_urlsafe(32)
    with get_conn() as conn:
        conn.execute("INSERT INTO sessions(user_id, token_hash, expires_at, last_seen_at) VALUES (?,?,?,?)",
                     (r["id"], _token_hash(token), _now(config.SESSION_HOURS), _now()))
    return {"token": token, "expires_in_hours": config.SESSION_HOURS, "user": _public(r)}


def user_from_token(token: str) -> dict | None:
    if not token:
        return None
    with get_conn() as conn:
        r = conn.execute("""SELECT u.*, s.id AS session_id FROM sessions s JOIN users u ON u.id=s.user_id
                            WHERE s.token_hash=? AND s.expires_at > ? AND u.active=1""",
                         (_token_hash(token), _now())).fetchone()
        if r:
            conn.execute("UPDATE sessions SET last_seen_at=? WHERE id=?", (_now(), r["session_id"]))
    if not r:
        return None
    d = _public(r)
    d.pop("session_id", None)
    return d


def logout(token: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))


# ------------------------------------------------------------------ projetos: equipe e permissões
def project_role(u: dict, pid: int) -> str | None:
    if u.get("role") == "admin":
        return "dono"
    with get_conn() as conn:
        r = conn.execute("SELECT role FROM project_members WHERE project_id=? AND user_id=?", (pid, u.get("id"))).fetchone()
    return r["role"] if r else None


def accessible_project_ids(u: dict) -> set[int] | None:
    """None = todos (admin/uso local)."""
    if u.get("role") == "admin":
        return None
    with get_conn() as conn:
        return {r["project_id"] for r in conn.execute("SELECT project_id FROM project_members WHERE user_id=?",
                                                       (u.get("id"),))}


def check_project(u: dict, pid: int, write: bool) -> None:
    role = project_role(u, pid)
    if role is None:
        raise Forbidden("Você não faz parte da equipe deste projeto.")
    if write and role == "leitor":
        raise Forbidden("Seu papel neste projeto é somente leitura.")


def add_creator_as_owner(pid: int) -> None:
    u = user()
    if u.get("id"):
        with get_conn() as conn:
            conn.execute("INSERT INTO project_members(project_id, user_id, role) VALUES (?,?,?)", (pid, u["id"], "dono"))


def list_members(pid: int) -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT u.id AS user_id, u.email, u.name, m.role, m.created_at FROM project_members m
               JOIN users u ON u.id=m.user_id WHERE m.project_id=? ORDER BY u.email""", (pid,))]


def set_member(pid: int, email: str, role: str) -> list[dict]:
    if role not in PROJECT_ROLES:
        raise AuthError(f"Papel inválido. Use: {', '.join(PROJECT_ROLES)}.")
    with get_conn() as conn:
        r = conn.execute("SELECT id FROM users WHERE email=?", ((email or "").strip().lower(),)).fetchone()
        if not r:
            raise AuthError("Usuário não encontrado (o administrador precisa cadastrá-lo antes).")
        conn.execute("DELETE FROM project_members WHERE project_id=? AND user_id=?", (pid, r["id"]))
        conn.execute("INSERT INTO project_members(project_id, user_id, role) VALUES (?,?,?)", (pid, r["id"], role))
    return list_members(pid)


def remove_member(pid: int, uid: int) -> list[dict]:
    with get_conn() as conn:
        owners = [x["user_id"] for x in conn.execute(
            "SELECT user_id FROM project_members WHERE project_id=? AND role='dono'", (pid,))]
        if owners == [uid]:
            raise AuthError("O projeto precisa de pelo menos um dono.")
        conn.execute("DELETE FROM project_members WHERE project_id=? AND user_id=?", (pid, uid))
    return list_members(pid)


# ------------------------------------------------------------------ auditoria
def audit(user_id, email, action: str, status: int | None = None, ip: str = "", detail: dict | None = None) -> None:
    try:
        with get_conn() as conn:
            conn.execute("INSERT INTO audit_log(user_id, email, action, status, ip, detail) VALUES (?,?,?,?,?,?)",
                         (user_id, email, action, status, ip, json.dumps(detail or {}, ensure_ascii=False)))
    except Exception:  # auditoria nunca derruba a operação
        log.exception("Falha ao registrar auditoria")


def list_audit(limit: int = 200) -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]


# ------------------------------------------------------------------ autorização central por rota
def project_of(kind: str, oid: int) -> int | None:
    sql = {"file": "SELECT project_id FROM project_files WHERE id=?",
           "model": "SELECT project_id FROM ifc_models WHERE id=?",
           "element": "SELECT project_id FROM ifc_elements WHERE id=?",
           "memorial": "SELECT project_id FROM memorials WHERE id=?",
           "chapter": "SELECT m.project_id FROM memorial_chapters c JOIN memorials m ON m.id=c.memorial_id WHERE c.id=?",
           "job": "SELECT project_id FROM jobs WHERE id=?"}[kind]
    with get_conn() as conn:
        r = conn.execute(sql, (oid,)).fetchone()
    return r[0] if r else None


_RULES = [  # (padrão da rota, tipo do objeto)
    (re.compile(r"^/api/projects/(\d+)(/.*)?$"), "project"),
    (re.compile(r"^/api/ifc-models/(\d+)(/.*)?$"), "model"),
    (re.compile(r"^/api/ifc-elements/(\d+)(/.*)?$"), "element"),
    (re.compile(r"^/api/memorials/(\d+)(/.*)?$"), "memorial"),
    (re.compile(r"^/api/memorial-chapters/(\d+)(/.*)?$"), "chapter"),
    (re.compile(r"^/api/jobs/(\d+)(/.*)?$"), "job"),
]


def authorize(u: dict, method: str, path: str, query: dict) -> None:
    """Decide se o usuário pode fazer a requisição. Lança Forbidden. Negado por padrão em rotas desconhecidas
    que alteram dados (exceto admin)."""
    write = method not in ("GET", "HEAD", "OPTIONS")
    role = u.get("role")
    if role == "admin":
        return
    if path in ("/api/auth/me", "/api/auth/logout"):
        return
    if path.startswith(("/api/users", "/api/audit")):
        raise Forbidden("Somente administradores.")
    if path.startswith(("/api/library", "/api/search")):
        if write and role != "editor":
            raise Forbidden("Somente editores alteram a biblioteca de memoriais.")
        return
    if path == "/api/projects":
        if write and role != "editor":
            raise Forbidden("Somente editores criam projetos.")
        return  # a lista já é filtrada pela equipe
    if path in ("/api/memorials",):
        return  # filtrada
    if path == "/api/jobs":
        pid = query.get("project_id")
        if not pid:
            raise Forbidden("Informe o projeto.")
        check_project(u, int(pid), False)
        return
    for rx, kind in _RULES:
        m = rx.match(path)
        if m:
            oid = int(m.group(1))
            pid = oid if kind == "project" else project_of(kind, oid)
            if pid is None:
                return  # inexistente: a rota responde 404
            owner_only = kind == "project" and write and (
                (m.group(2) or "").startswith("/members") or (method == "DELETE" and not m.group(2)))
            check_project(u, pid, write)
            if owner_only and project_role(u, pid) != "dono":
                raise Forbidden("Só o dono do projeto gerencia a equipe ou exclui o projeto.")
            return
    if write:
        raise Forbidden("Operação não permitida para o seu papel.")
