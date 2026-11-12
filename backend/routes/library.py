from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from backend import config
from backend.schemas.document import ChunkOut, DocumentOut, SectionOut, TextHit
from backend.services import library_service as svc

router = APIRouter(prefix="/api/library", tags=["biblioteca"])
log = logging.getLogger("bimoffice.routes.library")


def _http(e: svc.LibraryError) -> HTTPException:
    if isinstance(e, svc.NotFound):
        return HTTPException(404, str(e))
    if isinstance(e, svc.DuplicateDocument):
        return HTTPException(409, str(e))
    return HTTPException(400, str(e))


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def import_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    unit: str = Form(""),
    project: str = Form(""),
    discipline: str = Form(""),
    doc_date: str = Form(""),
    description: str = Form(""),
    tags: str = Form(""),
):
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    meta = dict(title=title, unit=unit, project=project, discipline=discipline,
                doc_date=doc_date, description=description, tags=tags)
    try:
        return svc.import_document(file.filename or "", data, meta)
    except svc.LibraryError as e:
        raise _http(e)
    except Exception:
        log.exception("Erro inesperado ao importar")
        raise HTTPException(500, "Erro ao processar o documento. Veja data/logs/bimoffice.log.")


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(unit: str = "", project: str = "", discipline: str = "",
                   tag: str = "", q: str = "", include_deleted: bool = False):
    return svc.list_documents(unit, project, discipline, tag, q, include_deleted)


@router.get("/documents/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int):
    try:
        return svc.get_document(doc_id)
    except svc.LibraryError as e:
        raise _http(e)


@router.patch("/documents/{doc_id}", response_model=DocumentOut)
def update_document(doc_id: int, meta: dict):
    try:
        return svc.update_metadata(doc_id, meta)
    except svc.LibraryError as e:
        raise _http(e)


@router.get("/documents/{doc_id}/sections", response_model=list[SectionOut])
def sections(doc_id: int):
    try:
        return svc.list_sections(doc_id)
    except svc.LibraryError as e:
        raise _http(e)


@router.get("/documents/{doc_id}/chunks", response_model=list[ChunkOut])
def chunks(doc_id: int):
    try:
        return svc.list_chunks(doc_id)
    except svc.LibraryError as e:
        raise _http(e)


@router.get("/documents/{doc_id}/original")
def download_original(doc_id: int):
    """Baixa uma cópia do DOCX original (somente leitura; nunca é alterado)."""
    try:
        doc = svc.get_document(doc_id)
        return FileResponse(svc.original_path(doc_id), filename=doc["original_filename"])
    except svc.LibraryError as e:
        raise _http(e)


@router.post("/documents/{doc_id}/reindex", response_model=DocumentOut)
def reindex(doc_id: int):
    try:
        return svc.reindex_document(doc_id)
    except svc.LibraryError as e:
        raise _http(e)


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: int):
    try:
        svc.delete_document(doc_id)
    except svc.LibraryError as e:
        raise _http(e)


@router.post("/documents/{doc_id}/restore", response_model=DocumentOut)
def restore(doc_id: int):
    try:
        return svc.restore_document(doc_id)
    except svc.LibraryError as e:
        raise _http(e)


@router.get("/search-text", response_model=list[TextHit])
def search_text(q: str, limit: int = 20, unit: str = "", discipline: str = ""):
    return svc.search_text(q, limit, unit, discipline)


@router.post("/backup")
def backup():
    return {"backup": svc.backup_database().name}
