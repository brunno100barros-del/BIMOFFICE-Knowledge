"""API de projetos, arquivos, inventário IFC e tarefas em segundo plano."""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from pydantic import BaseModel

from backend import jobs
from backend.storage import file_response
from backend.projects import service as svc

router = APIRouter(prefix="/api", tags=["projetos e IFC"])
log = logging.getLogger("bimoffice.routes.projects")
MEDIA = {"ifc": "application/x-step", "pdf": "application/pdf", "image": None,
         "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def _http(e: svc.ProjectError) -> HTTPException:
    if isinstance(e, svc.NotFound):
        return HTTPException(404, str(e))
    if isinstance(e, svc.Duplicate):
        return HTTPException(409, {"message": str(e), "existing_file_id": e.existing["id"]})
    return HTTPException(400, str(e))


class ProjectIn(BaseModel):
    model_config = {"extra": "forbid"}
    name: str
    description: str = ""
    location: str = ""
    disciplines: list[str] = []


class ProjectPatch(BaseModel):
    model_config = {"extra": "forbid"}
    name: str | None = None
    description: str | None = None
    location: str | None = None
    disciplines: list[str] | None = None


@router.get("/projects")
def list_projects():
    return svc.list_projects()


@router.post("/projects", status_code=201)
def create_project(p: ProjectIn):
    try:
        return svc.create_project(p.name, p.description, p.location, p.disciplines)
    except svc.ProjectError as e:
        raise _http(e)


@router.get("/projects/{pid}")
def get_project(pid: int):
    try:
        return svc.get_project(pid)
    except svc.ProjectError as e:
        raise _http(e)


@router.patch("/projects/{pid}")
def update_project(pid: int, p: ProjectPatch):
    try:
        return svc.update_project(pid, p.model_dump(exclude_unset=True))
    except svc.ProjectError as e:
        raise _http(e)


@router.delete("/projects/{pid}", status_code=204)
def delete_project(pid: int):
    try:
        svc.delete_project(pid)
    except svc.ProjectError as e:
        raise _http(e)


@router.get("/projects/{pid}/history")
def project_history(pid: int):
    try:
        return svc.list_history(pid)
    except svc.ProjectError as e:
        raise _http(e)


@router.get("/projects/{pid}/files")
def list_files(pid: int):
    try:
        return svc.list_files(pid)
    except svc.ProjectError as e:
        raise _http(e)


@router.post("/projects/{pid}/files", status_code=201)
def upload_file(pid: int, file: UploadFile = File(...), discipline: str = Form("")):
    """Envia UM arquivo (IFC, PDF, DOCX, PNG, JPG). IFC é processado em segundo plano:
    a resposta traz a tarefa (`job`) para acompanhar o progresso."""
    try:
        f, job = svc.store_file(pid, file.filename or "", file.file, discipline)
        return {"file": f, "job": job}
    except svc.ProjectError as e:
        raise _http(e)
    except Exception:
        log.exception("Erro inesperado ao receber arquivo")
        raise HTTPException(500, "Erro ao receber o arquivo. Veja data/logs/bimoffice.log.")


@router.delete("/projects/{pid}/files/{fid}", status_code=204)
def delete_file(pid: int, fid: int):
    try:
        svc.delete_file(pid, fid)
    except svc.ProjectError as e:
        raise _http(e)


@router.post("/projects/{pid}/files/{fid}/reprocess")
def reprocess(pid: int, fid: int):
    try:
        return svc.reprocess(pid, fid)
    except svc.ProjectError as e:
        raise _http(e)


@router.get("/projects/{pid}/files/{fid}/original")
def original(pid: int, fid: int, inline: bool = False):
    try:
        f = svc.get_file(fid)
        if f["project_id"] != pid:
            raise svc.NotFound("Arquivo não encontrado neste projeto.")
        return file_response(svc.file_key(fid), f["original_filename"], MEDIA.get(f["kind"]), inline)
    except svc.ProjectError as e:
        raise _http(e)


@router.get("/projects/{pid}/ifc-models")
def list_models(pid: int):
    try:
        return svc.list_models(pid)
    except svc.ProjectError as e:
        raise _http(e)


@router.get("/ifc-models/{mid}")
def get_model(mid: int):
    try:
        return svc.get_model(mid)
    except svc.ProjectError as e:
        raise _http(e)


@router.get("/ifc-models/{mid}/elements")
def list_elements(mid: int, discipline: str = "", ifc_class: str = "", storey: str = "", q: str = "",
                  missing: str = "", limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    try:
        return svc.list_elements(mid, discipline, ifc_class, storey, q, missing, limit, offset)
    except svc.ProjectError as e:
        raise _http(e)


@router.get("/ifc-models/{mid}/export")
def export_inventory(mid: int):
    """Inventário completo em JSON (contrato `bimoffice.ifc-inventory/1`, para integrações)."""
    try:
        return svc.export_inventory(mid)
    except svc.ProjectError as e:
        raise _http(e)


@router.get("/ifc-elements/{eid}")
def get_element(eid: int):
    try:
        return svc.get_element(eid)
    except svc.ProjectError as e:
        raise _http(e)


@router.get("/jobs")
def list_jobs(project_id: int | None = None, active: bool = False):
    return jobs.list_jobs(project_id, active)


@router.get("/jobs/{jid}")
def get_job(jid: int):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "Tarefa não encontrada.")
    return j


@router.post("/jobs/{jid}/cancel")
def cancel_job(jid: int):
    j = jobs.cancel(jid)
    if not j:
        raise HTTPException(404, "Tarefa não encontrada.")
    return j
