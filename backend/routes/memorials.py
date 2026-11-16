"""API do memorial descritivo em elaboração (separado da biblioteca)."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from backend.memorials import service as svc
from backend.projects import service as projects

router = APIRouter(prefix="/api", tags=["memorial em elaboração"])


def _http(e: Exception) -> HTTPException:
    if isinstance(e, (svc.NotFound, projects.NotFound)):
        return HTTPException(404, str(e))
    if isinstance(e, svc.NotApproved):
        return HTTPException(409, str(e))
    return HTTPException(400, str(e))


ERRORS = (svc.MemorialError, projects.ProjectError)


class MemorialIn(BaseModel):
    model_config = {"extra": "forbid"}
    model_id: int | None = None
    title: str | None = None


class ChapterPatch(BaseModel):
    model_config = {"extra": "forbid"}
    text: str | None = None
    title: str | None = None


class ChapterNew(BaseModel):
    model_config = {"extra": "forbid"}
    title: str
    after_id: int | None = None


class TitleIn(BaseModel):
    model_config = {"extra": "forbid"}
    title: str


@router.get("/memorials")
def list_all():
    return svc.list_all()


@router.get("/projects/{pid}/memorials")
def list_memorials(pid: int):
    try:
        return svc.list_memorials(pid)
    except ERRORS as e:
        raise _http(e)


@router.post("/projects/{pid}/memorials", status_code=201)
def create_memorial(pid: int, body: MemorialIn):
    """Gera um memorial por capítulos a partir do inventário IFC (só dados do modelo) e
    busca trechos de referência na biblioteca como SUGESTÕES (não inseridos)."""
    try:
        return svc.create_memorial(pid, body.model_id, body.title)
    except ERRORS as e:
        raise _http(e)


@router.get("/memorials/{mid}")
def get_memorial(mid: int):
    try:
        return svc.get_memorial(mid)
    except ERRORS as e:
        raise _http(e)


@router.patch("/memorials/{mid}")
def rename_memorial(mid: int, body: TitleIn):
    try:
        return svc.rename_memorial(mid, body.title)
    except ERRORS as e:
        raise _http(e)


@router.delete("/memorials/{mid}", status_code=204)
def delete_memorial(mid: int):
    try:
        svc.delete_memorial(mid)
    except ERRORS as e:
        raise _http(e)


@router.post("/memorials/{mid}/chapters", status_code=201)
def add_chapter(mid: int, body: ChapterNew):
    try:
        return svc.add_chapter(mid, body.title, body.after_id)
    except ERRORS as e:
        raise _http(e)


@router.patch("/memorial-chapters/{cid}")
def update_chapter(cid: int, body: ChapterPatch):
    try:
        return svc.update_chapter(cid, body.text, body.title)
    except ERRORS as e:
        raise _http(e)


@router.delete("/memorial-chapters/{cid}")
def delete_chapter(cid: int):
    try:
        return svc.delete_chapter(cid)
    except ERRORS as e:
        raise _http(e)


@router.post("/memorial-chapters/{cid}/approve")
def approve(cid: int, approved: bool = True):
    try:
        return svc.set_status(cid, approved)
    except ERRORS as e:
        raise _http(e)


@router.post("/memorial-chapters/{cid}/insert-reference")
def insert_reference(cid: int, chunk_id: int):
    """Insere no capítulo um trecho da biblioteca escolhido pelo usuário (origem registrada)."""
    try:
        return svc.insert_reference(cid, chunk_id)
    except ERRORS as e:
        raise _http(e)


@router.post("/memorial-chapters/{cid}/suggestions")
def suggestions(cid: int, q: str = ""):
    try:
        return svc.refresh_suggestions(cid, q or None)
    except ERRORS as e:
        raise _http(e)


@router.post("/memorial-chapters/{cid}/regenerate")
def regenerate(cid: int, replace_text: bool = False):
    try:
        return svc.regenerate_chapter(cid, replace_text)
    except ERRORS as e:
        raise _http(e)


@router.post("/memorial-chapters/{cid}/move")
def move(cid: int, direction: int):
    try:
        return svc.move_chapter(cid, direction)
    except ERRORS as e:
        raise _http(e)


@router.get("/memorial-chapters/{cid}/history")
def history(cid: int):
    try:
        return svc.chapter_history(cid)
    except ERRORS as e:
        raise _http(e)


@router.get("/memorials/{mid}/export")
def export(mid: int, draft: bool = True):
    """DOCX. `draft=true`: minuta (sempre permitida, marcada). `draft=false`: final (todos aprovados)."""
    try:
        data, name = svc.export_docx(mid, draft)
    except ERRORS as e:
        raise _http(e)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
