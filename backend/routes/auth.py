"""Login, usuários (admin), equipe do projeto e auditoria."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend import auth

router = APIRouter(prefix="/api", tags=["acesso"])


def _http(e: auth.AuthError) -> HTTPException:
    return HTTPException(403 if isinstance(e, auth.Forbidden) else 400, str(e))


class LoginIn(BaseModel):
    model_config = {"extra": "forbid"}
    email: str
    password: str


class UserIn(BaseModel):
    model_config = {"extra": "forbid"}
    email: str
    name: str = ""
    password: str
    role: str = "leitor"


class UserPatch(BaseModel):
    model_config = {"extra": "forbid"}
    name: str | None = None
    role: str | None = None
    active: bool | None = None
    password: str | None = None


class MemberIn(BaseModel):
    model_config = {"extra": "forbid"}
    email: str
    role: str = "leitor"


@router.post("/auth/login")
def login(body: LoginIn, request: Request):
    try:
        return auth.login(body.email, body.password, request.client.host if request.client else "")
    except auth.AuthError as e:
        raise HTTPException(401, str(e))


@router.post("/auth/logout", status_code=204)
def logout(request: Request):
    tok = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if tok:
        auth.logout(tok)


@router.get("/auth/me")
def me():
    return auth.user()


@router.get("/users")
def list_users():
    return auth.list_users()


@router.post("/users", status_code=201)
def create_user(body: UserIn):
    try:
        return auth.create_user(body.email, body.name, body.password, body.role)
    except auth.AuthError as e:
        raise _http(e)


@router.patch("/users/{uid}")
def update_user(uid: int, body: UserPatch):
    try:
        return auth.update_user(uid, body.model_dump(exclude_unset=True))
    except auth.AuthError as e:
        raise _http(e)


@router.get("/projects/{pid}/members")
def members(pid: int):
    return auth.list_members(pid)


@router.post("/projects/{pid}/members")
def set_member(pid: int, body: MemberIn):
    try:
        return auth.set_member(pid, body.email, body.role)
    except auth.AuthError as e:
        raise _http(e)


@router.delete("/projects/{pid}/members/{uid}")
def remove_member(pid: int, uid: int):
    try:
        return auth.remove_member(pid, uid)
    except auth.AuthError as e:
        raise _http(e)


@router.get("/audit")
def audit(limit: int = 200):
    return auth.list_audit(min(limit, 1000))
