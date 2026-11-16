"""Projetos de engenharia: arquivos (IFC, PDF, DOCX, imagens), versões, histórico e inventário IFC.

Regras:
- Originais guardados em data/projects/<sha256>.<ext>, SOMENTE LEITURA, nunca alterados.
- Mesmo conteúdo no mesmo projeto = duplicado (recusado). Mesmo nome com conteúdo novo = nova versão.
- Processamento pesado (IFC) roda em segundo plano (backend.jobs), nunca dentro da requisição.
- Projetos são separados da biblioteca de memoriais.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path
from typing import BinaryIO

from backend import config, jobs
from backend.database.db import get_conn
from backend.ifc.inventory import build_summary

log = logging.getLogger("bimoffice.projects")


class ProjectError(Exception):
    pass


class NotFound(ProjectError):
    pass


class InvalidFile(ProjectError):
    pass


class Duplicate(ProjectError):
    def __init__(self, existing: dict):
        super().__init__(f"Este arquivo já está no projeto: «{existing['original_filename']}» "
                         f"(versão {existing['version']}).")
        self.existing = existing


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def history(project_id: int, event: str, detail: dict | None = None, conn=None) -> None:
    sql = "INSERT INTO project_history(project_id, event, detail) VALUES (?,?,?)"
    if conn is not None:
        conn.execute(sql, (project_id, event, _j(detail or {})))
    else:
        with get_conn() as c:
            c.execute(sql, (project_id, event, _j(detail or {})))


# ------------------------------------------------------------------ projetos
def _project_row(r) -> dict:
    d = dict(r)
    d["disciplines"] = json.loads(d.get("disciplines") or "[]")
    return d


def create_project(name: str, description: str = "", location: str = "",
                   disciplines: list[str] | None = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ProjectError("Informe o nome do projeto.")
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO projects(name, description, location, disciplines) VALUES (?,?,?,?)",
                           (name, description.strip(), location.strip(), _j(disciplines or [])))
        pid = cur.lastrowid
        history(pid, "projeto criado", {"nome": name}, conn)
    return get_project(pid)


def get_project(pid: int) -> dict:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM projects WHERE id=? AND deleted_at IS NULL", (pid,)).fetchone()
        if not r:
            raise NotFound("Projeto não encontrado.")
        d = _project_row(r)
        c = conn.execute("""SELECT kind, COUNT(*) n FROM project_files WHERE project_id=? AND deleted_at IS NULL
                            GROUP BY kind""", (pid,)).fetchall()
        d["file_counts"] = {x["kind"]: x["n"] for x in c}
        d["ifc_models"] = conn.execute("SELECT COUNT(*) FROM ifc_models m JOIN project_files f ON f.id=m.file_id "
                                       "WHERE m.project_id=? AND f.deleted_at IS NULL", (pid,)).fetchone()[0]
    return d


def list_projects() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT id FROM projects WHERE deleted_at IS NULL ORDER BY updated_at DESC, id DESC")
        ids = [r["id"] for r in rows]
    return [get_project(i) for i in ids]


def update_project(pid: int, fields: dict) -> dict:
    before = get_project(pid)
    allowed = {k: v for k, v in fields.items() if k in ("name", "description", "location", "disciplines") and v is not None}
    if "name" in allowed and not str(allowed["name"]).strip():
        raise ProjectError("O nome do projeto não pode ficar vazio.")
    if not allowed:
        return before
    vals = {k: (_j(v) if k == "disciplines" else str(v).strip()) for k, v in allowed.items()}
    with get_conn() as conn:
        conn.execute(f"UPDATE projects SET {', '.join(f'{k}=?' for k in vals)}, updated_at=datetime('now') WHERE id=?",
                     (*vals.values(), pid))
        history(pid, "dados do projeto alterados",
                {k: {"antes": before.get(k), "depois": allowed[k]} for k in allowed}, conn)
    return get_project(pid)


def delete_project(pid: int) -> None:
    get_project(pid)
    with get_conn() as conn:
        conn.execute("UPDATE projects SET deleted_at=datetime('now') WHERE id=?", (pid,))
        history(pid, "projeto movido para a lixeira", {}, conn)


def list_history(pid: int) -> list[dict]:
    get_project(pid)
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM project_history WHERE project_id=? ORDER BY id DESC", (pid,)).fetchall()
    return [{**dict(r), "detail": json.loads(r["detail"])} for r in rows]


# ------------------------------------------------------------------ arquivos
def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.\- ()]", "_", Path(name or "arquivo").name)[:200]


def _validate(kind: str, head: bytes, filename: str) -> None:
    if kind == "ifc" and b"ISO-10303-21" not in head[:64]:
        raise InvalidFile("O arquivo não parece ser um IFC (formato STEP .ifc). IFCZIP e ifcXML ainda não são aceitos.")
    if kind == "pdf" and b"%PDF-" not in head[:1024]:
        raise InvalidFile("O arquivo não parece ser um PDF válido.")
    if kind == "docx" and not head.startswith(b"PK"):
        raise InvalidFile("O arquivo não parece ser um DOCX válido.")
    if kind == "image" and not (head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8")):
        raise InvalidFile("A imagem não parece ser PNG ou JPEG válido.")


def store_file(pid: int, filename: str, stream: BinaryIO, discipline: str = "") -> tuple[dict, dict | None]:
    """Grava o arquivo (em partes, sem carregar tudo na memória). Retorna (arquivo, tarefa)."""
    get_project(pid)
    ext = Path(filename or "").suffix.lower()
    if ext == ".dwg":
        raise InvalidFile("DWG ainda não é suportado: exporte o desenho como IFC, PDF ou DXF. "
                          "(Veja docs/IFC.md — estratégia para DWG.)")
    kind = config.PROJECT_EXTENSIONS.get(ext)
    if not kind:
        raise InvalidFile("Tipo não aceito. Use IFC, PDF, DOCX, PNG ou JPG.")
    limit = config.MAX_IFC_BYTES if kind == "ifc" else config.MAX_UPLOAD_BYTES
    config.PROJECT_FILES_DIR.mkdir(parents=True, exist_ok=True)
    h, size, head = hashlib.sha256(), 0, b""
    fd, tmp = tempfile.mkstemp(dir=config.PROJECT_FILES_DIR, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                if not head:
                    head = chunk[:2048]
                size += len(chunk)
                if size > limit:
                    raise InvalidFile(f"Arquivo maior que o limite de {limit // (1024 * 1024)} MB.")
                h.update(chunk)
                out.write(chunk)
        if size == 0:
            raise InvalidFile("O arquivo está vazio.")
        _validate(kind, head, filename)
        sha = h.hexdigest()
        safe = _safe_name(filename)
        with get_conn() as conn:
            dup = conn.execute("""SELECT * FROM project_files WHERE project_id=? AND sha256=? AND deleted_at IS NULL""",
                               (pid, sha)).fetchone()
            if dup:
                raise Duplicate(dict(dup))
            prev = conn.execute("""SELECT * FROM project_files WHERE project_id=? AND lower(original_filename)=lower(?)
                                   AND deleted_at IS NULL ORDER BY version DESC LIMIT 1""", (pid, safe)).fetchone()
        stored_rel = f"{sha}{ext}"
        dest = config.PROJECT_FILES_DIR / stored_rel
        if dest.exists():
            os.unlink(tmp)  # mesmo conteúdo já guardado (outro projeto): reaproveita, não duplica no disco
        else:
            shutil.move(tmp, dest)
            os.chmod(dest, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        version = (prev["version"] + 1) if prev else 1
        with get_conn() as conn:
            cur = conn.execute("""INSERT INTO project_files(project_id, kind, original_filename, sha256, stored_path,
                                  size_bytes, discipline, version, previous_file_id, status)
                                  VALUES (?,?,?,?,?,?,?,?,?,?)""",
                               (pid, kind, safe, sha, stored_rel, size, discipline.strip(), version,
                                prev["id"] if prev else None, "na fila" if kind == "ifc" else "armazenado"))
            fid = cur.lastrowid
            conn.execute("UPDATE projects SET updated_at=datetime('now') WHERE id=?", (pid,))
            history(pid, "arquivo adicionado" if version == 1 else "nova versão de arquivo",
                    {"arquivo": safe, "tipo": kind, "versão": version, "sha256": sha[:16]}, conn)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    job = jobs.enqueue("ifc_parse", pid, fid) if kind == "ifc" else None
    return get_file(fid), job


def get_file(fid: int) -> dict:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM project_files WHERE id=?", (fid,)).fetchone()
        if not r:
            raise NotFound("Arquivo não encontrado.")
        d = dict(r)
        m = conn.execute("SELECT id, schema_name, n_elements FROM ifc_models WHERE file_id=?", (fid,)).fetchone()
        d["ifc_model"] = dict(m) if m else None
        j = conn.execute("SELECT * FROM jobs WHERE target_id=? AND kind='ifc_parse' ORDER BY id DESC LIMIT 1",
                         (fid,)).fetchone()
        d["last_job"] = dict(j) if j else None
    d.pop("stored_path", None)
    return d


def list_files(pid: int) -> list[dict]:
    get_project(pid)
    with get_conn() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM project_files WHERE project_id=? AND deleted_at IS NULL ORDER BY id DESC", (pid,))]
    return [get_file(i) for i in ids]


def file_path(fid: int) -> Path:
    with get_conn() as conn:
        r = conn.execute("SELECT stored_path FROM project_files WHERE id=? AND deleted_at IS NULL", (fid,)).fetchone()
    if not r:
        raise NotFound("Arquivo não encontrado.")
    return config.PROJECT_FILES_DIR / r["stored_path"]


def delete_file(pid: int, fid: int) -> None:
    f = get_file(fid)
    if f["project_id"] != pid or f["deleted_at"]:
        raise NotFound("Arquivo não encontrado neste projeto.")
    with get_conn() as conn:
        conn.execute("UPDATE project_files SET deleted_at=datetime('now') WHERE id=?", (fid,))
        conn.execute("""UPDATE jobs SET cancel_requested=1 WHERE target_id=? AND kind='ifc_parse'
                        AND status IN ('na fila','executando')""", (fid,))
        history(pid, "arquivo removido do projeto", {"arquivo": f["original_filename"], "versão": f["version"]}, conn)


def reprocess(pid: int, fid: int) -> dict:
    f = get_file(fid)
    if f["project_id"] != pid or f["deleted_at"] or f["kind"] != "ifc":
        raise ProjectError("Só modelos IFC deste projeto podem ser reprocessados.")
    with get_conn() as conn:
        conn.execute("UPDATE project_files SET status='na fila', error=NULL WHERE id=?", (fid,))
        history(pid, "reprocessamento solicitado", {"arquivo": f["original_filename"]}, conn)
    return jobs.enqueue("ifc_parse", pid, fid)


# ------------------------------------------------------------------ processamento IFC (segundo plano)
@jobs.handler("ifc_parse")
def _job_ifc_parse(job: dict, ctx: jobs.JobContext) -> None:
    from backend.ifc.reader import Cancelled, IfcReadError, read_ifc

    fid, pid = job["target_id"], job["project_id"]
    f = get_file(fid)
    if f["deleted_at"]:
        raise jobs.JobCancelled()
    with get_conn() as conn:
        conn.execute("UPDATE project_files SET status='processando', error=NULL WHERE id=?", (fid,))
    try:
        result = read_ifc(file_path(fid), progress=ctx.progress, should_cancel=ctx.cancelled,
                          geometry=True, geometry_seconds=config.IFC_GEOMETRY_SECONDS)
    except Cancelled:
        with get_conn() as conn:
            conn.execute("UPDATE project_files SET status='cancelado' WHERE id=?", (fid,))
        raise jobs.JobCancelled()
    except IfcReadError as e:
        with get_conn() as conn:
            conn.execute("UPDATE project_files SET status='erro', error=? WHERE id=?", (str(e), fid))
        history(pid, "erro ao ler IFC", {"arquivo": f["original_filename"], "erro": str(e)})
        raise
    except Exception as e:
        with get_conn() as conn:
            conn.execute("UPDATE project_files SET status='erro', error=? WHERE id=?",
                         (f"Erro inesperado: {type(e).__name__}: {e}", fid))
        raise
    ctx.progress(0.97, "Gravando inventário…")
    summary = build_summary(result)
    with get_conn() as conn:  # grava tudo numa transação (substitui leitura anterior do mesmo arquivo)
        old = conn.execute("SELECT id FROM ifc_models WHERE file_id=?", (fid,)).fetchone()
        if old:
            conn.execute("DELETE FROM ifc_elements WHERE model_id=?", (old["id"],))
            conn.execute("DELETE FROM ifc_models WHERE id=?", (old["id"],))
        cur = conn.execute("""INSERT INTO ifc_models(file_id, project_id, schema_name, header, units, summary,
                              n_elements, parse_seconds) VALUES (?,?,?,?,?,?,?,?)""",
                           (fid, pid, result["header"]["schema"], _j(result["header"]), _j(result["units"]),
                            _j(summary), len(result["elements"]), result["parse_seconds"]))
        mid = cur.lastrowid
        conn.executemany(
            """INSERT INTO ifc_elements(model_id, project_id, global_id, ifc_class, predefined_type, name,
               type_name, storey, discipline, confidence, missing, data) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(mid, pid, e.get("global_id"), e["ifc_class"], e.get("predefined_type"), e.get("name"),
              e.get("type_name"), e.get("storey"), e["discipline"], e["confidence"], _j(e.get("missing") or []),
              _j(e)) for e in result["elements"]])
        conn.execute("UPDATE project_files SET status='processado', error=NULL WHERE id=?", (fid,))
        conn.execute("UPDATE projects SET updated_at=datetime('now') WHERE id=?", (pid,))
        history(pid, "IFC processado", {"arquivo": f["original_filename"], "versão": f["version"],
                                        "schema": result["header"]["schema"], "elementos": len(result["elements"]),
                                        "segundos": result["parse_seconds"]}, conn)


# ------------------------------------------------------------------ consulta do inventário
def _model_row(r) -> dict:
    d = dict(r)
    for k in ("header", "units", "summary"):
        d[k] = json.loads(d[k] or "{}")
    return d


def list_models(pid: int) -> list[dict]:
    get_project(pid)
    with get_conn() as conn:
        rows = conn.execute("""SELECT m.*, f.original_filename, f.version, f.discipline AS file_discipline
                               FROM ifc_models m JOIN project_files f ON f.id=m.file_id
                               WHERE m.project_id=? AND f.deleted_at IS NULL ORDER BY m.id DESC""", (pid,)).fetchall()
    return [_model_row(r) for r in rows]


def get_model(mid: int) -> dict:
    with get_conn() as conn:
        r = conn.execute("""SELECT m.*, f.original_filename, f.version, f.discipline AS file_discipline
                            FROM ifc_models m JOIN project_files f ON f.id=m.file_id
                            WHERE m.id=? AND f.deleted_at IS NULL""", (mid,)).fetchone()
    if not r:
        raise NotFound("Modelo IFC não encontrado.")
    return _model_row(r)


def list_elements(mid: int, discipline: str = "", ifc_class: str = "", storey: str = "", q: str = "",
                  missing: str = "", limit: int = 100, offset: int = 0) -> dict:
    get_model(mid)
    sql, params = " FROM ifc_elements WHERE model_id=?", [mid]
    for col, val in (("discipline", discipline), ("ifc_class", ifc_class)):
        if val:
            sql += f" AND {col}=?"
            params.append(val)
    if storey:
        if storey == "(sem pavimento)":
            sql += " AND storey IS NULL"
        else:
            sql += " AND storey=?"
            params.append(storey)
    if q:
        sql += " AND (name LIKE ? OR global_id LIKE ? OR type_name LIKE ?)"
        params += [f"%{q}%"] * 3
    if missing == "any":
        sql += " AND missing != '[]'"
    elif missing:
        sql += " AND missing LIKE ?"
        params.append(f'%"{missing}"%')
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*)" + sql, params).fetchone()[0]
        rows = conn.execute("SELECT id, global_id, ifc_class, predefined_type, name, type_name, storey, discipline, "
                            "confidence, missing" + sql + " ORDER BY ifc_class, name LIMIT ? OFFSET ?",
                            [*params, limit, offset]).fetchall()
    return {"total": total, "limit": limit, "offset": offset,
            "items": [{**dict(r), "missing": json.loads(r["missing"])} for r in rows]}


def get_element(eid: int) -> dict:
    with get_conn() as conn:
        r = conn.execute("SELECT id, model_id, project_id, data FROM ifc_elements WHERE id=?", (eid,)).fetchone()
    if not r:
        raise NotFound("Elemento não encontrado.")
    return {"id": r["id"], "model_id": r["model_id"], "project_id": r["project_id"], **json.loads(r["data"])}


def export_inventory(mid: int) -> dict:
    """Contrato estável para integrações (ex.: Coordix). Versão no campo `format`."""
    m = get_model(mid)
    with get_conn() as conn:
        rows = conn.execute("SELECT data FROM ifc_elements WHERE model_id=? ORDER BY id", (mid,)).fetchall()
    return {"format": "bimoffice.ifc-inventory/1", "model": {k: m[k] for k in (
        "id", "project_id", "schema_name", "header", "units", "n_elements", "original_filename", "version")},
        "summary": m["summary"], "elements": [json.loads(r["data"]) for r in rows]}
