"""Regras de negócio da biblioteca de memoriais.

Garantias:
- O DOCX original é copiado para data/documents/ (nome = hash SHA-256) e marcado
  como somente leitura. Nenhuma rotina grava nele; reindexar apenas relê.
- Exclusão é lógica (lixeira). Antes de excluir/reindexar, é feito backup do banco.
- Documentos são tratados como DADOS; nenhum texto deles é interpretado como comando.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import stat
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

from backend import config
from backend.database.db import get_conn
from backend.document_processing.chunker import chunk_document
from backend.document_processing.docx_parser import parse_docx

log = logging.getLogger("bimoffice.library")


class LibraryError(Exception):
    """Erro de regra de negócio com mensagem apropriada ao usuário."""


class InvalidFile(LibraryError):
    pass


class DuplicateDocument(LibraryError):
    def __init__(self, existing_id: int, title: str):
        super().__init__(f"Este arquivo já está na biblioteca: «{title}» (id {existing_id}).")
        self.existing_id = existing_id


class NotFound(LibraryError):
    pass


# ------------------------------------------------------------------ validação
def validate_upload(filename: str, data: bytes) -> None:
    ext = Path(filename or "").suffix.lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise InvalidFile("Somente arquivos .docx são aceitos.")
    if not data:
        raise InvalidFile("O arquivo está vazio.")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise InvalidFile(f"Arquivo maior que {config.MAX_UPLOAD_BYTES // (1024*1024)} MB.")
    # DOCX é um ZIP contendo word/document.xml
    try:
        with zipfile.ZipFile(BytesIO(data)) as z:
            if "word/document.xml" not in z.namelist():
                raise InvalidFile("O arquivo não parece ser um DOCX válido.")
            total = sum(i.file_size for i in z.infolist())
            if total > 500 * 1024 * 1024:  # proteção contra "zip bomb"
                raise InvalidFile("Conteúdo descompactado grande demais.")
    except zipfile.BadZipFile:
        raise InvalidFile("O arquivo não parece ser um DOCX válido.")


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.\- ]", "_", Path(name).name)[:200]


# ------------------------------------------------------------------ conversão
def _doc_row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d.pop("stored_path", None)
    d["tags"] = json.loads(d.get("tags") or "[]")
    return d


def _parse_tags(tags) -> list[str]:
    if isinstance(tags, str):
        tags = [t for t in re.split(r"[,;]", tags)]
    return sorted({t.strip() for t in (tags or []) if t and t.strip()})


# ------------------------------------------------------------------ backup
def backup_database() -> Path:
    config.ensure_dirs()
    dest = config.BACKUPS_DIR / f"bimoffice_{datetime.now():%Y%m%d_%H%M%S_%f}.db"
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    log.info("Backup criado: %s", dest)
    return dest


# ------------------------------------------------------------------ indexação
def _index_file(conn: sqlite3.Connection, document_id: int, path: Path) -> tuple[int, int]:
    """(Re)cria seções e trechos de um documento a partir do arquivo armazenado."""
    parsed = parse_docx(path)
    chunks = chunk_document(parsed)
    if not chunks:
        raise InvalidFile("Não foi encontrado texto no documento.")

    conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
    conn.execute("DELETE FROM sections WHERE document_id = ?", (document_id,))

    section_ids: dict[int, int] = {}
    for i, s in enumerate(parsed.sections):
        cur = conn.execute(
            "INSERT INTO sections(document_id, level, title, path, position) VALUES (?,?,?,?,?)",
            (document_id, s.level, s.title, s.path, s.position),
        )
        section_ids[i] = cur.lastrowid

    for c in chunks:
        conn.execute(
            """INSERT INTO chunks(document_id, section_id, section_path, position_start,
                                  position_end, est_page, text, char_count)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                document_id, section_ids.get(c.section_index), c.section_path,
                c.position_start, c.position_end, c.est_page, c.text, len(c.text),
            ),
        )
    conn.execute(
        "UPDATE documents SET n_sections=?, n_chunks=?, indexed_at=datetime('now') WHERE id=?",
        (len(parsed.sections), len(chunks), document_id),
    )
    return len(parsed.sections), len(chunks)


# ------------------------------------------------------------------ operações
def import_document(filename: str, data: bytes, meta: dict) -> dict:
    config.ensure_dirs()
    validate_upload(filename, data)
    sha = hashlib.sha256(data).hexdigest()

    with get_conn() as conn:
        dup = conn.execute(
            "SELECT id, title FROM documents WHERE sha256=? AND deleted_at IS NULL", (sha,)
        ).fetchone()
        if dup:
            raise DuplicateDocument(dup["id"], dup["title"])

    stored_rel = f"{sha}.docx"
    stored = config.DOCUMENTS_DIR / stored_rel
    created_file = False
    if not stored.exists():
        stored.write_bytes(data)
        os.chmod(stored, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # somente leitura
        created_file = True

    try:
        with get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO documents(title, unit, project, discipline, doc_date,
                       description, tags, original_filename, sha256, stored_path)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    (meta.get("title") or Path(filename).stem).strip(),
                    (meta.get("unit") or "").strip(),
                    (meta.get("project") or "").strip(),
                    (meta.get("discipline") or "").strip(),
                    (meta.get("doc_date") or "").strip(),
                    (meta.get("description") or "").strip(),
                    json.dumps(_parse_tags(meta.get("tags"))),
                    _safe_name(filename), sha, stored_rel,
                ),
            )
            doc_id = cur.lastrowid
            _index_file(conn, doc_id, stored)
    except Exception:
        log.exception("Falha ao importar %s", filename)
        if created_file:  # não deixa arquivo órfão
            os.chmod(stored, stat.S_IRUSR | stat.S_IWUSR)
            stored.unlink(missing_ok=True)
        raise
    log.info("Documento %s importado (id %s)", filename, doc_id)
    return get_document(doc_id)


def get_document(doc_id: int, include_deleted: bool = False) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not row or (row["deleted_at"] and not include_deleted):
        raise NotFound("Documento não encontrado.")
    return _doc_row_to_dict(row)


def list_documents(
    unit: str = "", project: str = "", discipline: str = "", tag: str = "",
    q: str = "", include_deleted: bool = False,
) -> list[dict]:
    sql, params = "SELECT * FROM documents WHERE 1=1", []
    if not include_deleted:
        sql += " AND deleted_at IS NULL"
    for col, val in (("unit", unit), ("project", project), ("discipline", discipline)):
        if val:
            sql += f" AND {col} = ? COLLATE NOCASE"
            params.append(val)
    if q:
        sql += " AND (title LIKE ? OR description LIKE ? OR original_filename LIKE ?)"
        params += [f"%{q}%"] * 3
    sql += " ORDER BY created_at DESC, id DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    docs = [_doc_row_to_dict(r) for r in rows]
    if tag:
        docs = [d for d in docs if tag.lower() in (t.lower() for t in d["tags"])]
    return docs


def list_sections(doc_id: int) -> list[dict]:
    get_document(doc_id)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, level, title, path, position FROM sections WHERE document_id=? ORDER BY position",
            (doc_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_chunks(doc_id: int) -> list[dict]:
    get_document(doc_id)
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, section_path, position_start, position_end, est_page, text
               FROM chunks WHERE document_id=? ORDER BY position_start, id""",
            (doc_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_metadata(doc_id: int, meta: dict) -> dict:
    get_document(doc_id)
    fields = {k: (v or "").strip() for k, v in meta.items()
              if k in {"title", "unit", "project", "discipline", "doc_date", "description"} and v is not None}
    if "tags" in meta and meta["tags"] is not None:
        fields["tags"] = json.dumps(_parse_tags(meta["tags"]))
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        with get_conn() as conn:
            conn.execute(f"UPDATE documents SET {sets} WHERE id=?", (*fields.values(), doc_id))
    return get_document(doc_id)


def delete_document(doc_id: int) -> None:
    """Exclusão lógica: o arquivo e os dados permanecem; o documento sai das listas/buscas."""
    get_document(doc_id)
    backup_database()
    with get_conn() as conn:
        conn.execute("UPDATE documents SET deleted_at=datetime('now') WHERE id=?", (doc_id,))
        conn.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))  # sai da busca (FTS via trigger)
        conn.execute("DELETE FROM sections WHERE document_id=?", (doc_id,))
    log.info("Documento %s movido para a lixeira", doc_id)


def restore_document(doc_id: int) -> dict:
    doc = get_document(doc_id, include_deleted=True)
    if not doc["deleted_at"]:
        return doc
    with get_conn() as conn:
        dup = conn.execute(
            "SELECT id, title FROM documents WHERE sha256=? AND deleted_at IS NULL", (doc["sha256"],)
        ).fetchone()
        if dup:
            raise DuplicateDocument(dup["id"], dup["title"])
        conn.execute("UPDATE documents SET deleted_at=NULL WHERE id=?", (doc_id,))
        _index_file(conn, doc_id, config.DOCUMENTS_DIR / f"{doc['sha256']}.docx")
    return get_document(doc_id)


def reindex_document(doc_id: int) -> dict:
    doc = get_document(doc_id)
    stored = config.DOCUMENTS_DIR / f"{doc['sha256']}.docx"
    if not stored.exists():
        raise LibraryError("O arquivo original não foi encontrado em data/documents.")
    backup_database()
    with get_conn() as conn:
        _index_file(conn, doc_id, stored)
    return get_document(doc_id)


def original_path(doc_id: int) -> Path:
    doc = get_document(doc_id)
    return config.DOCUMENTS_DIR / f"{doc['sha256']}.docx"


# ------------------------------------------------------------------ busca textual
# Palavras sem conteúdo técnico, ignoradas no modo "qualquer palavra" (pesquisa híbrida).
STOPWORDS_PT = set("""
a à ao aos as às o os um uma uns umas de da do das dos dum duma em na no nas nos num numa
e ou mas que se com sem por pela pelo pelas pelos para pra sob sobre entre até após ante
é ser será serão são foi foram sendo seja sejam está estão estar ter terá terão tem têm
deve devem deverá deverão haverá cada todo toda todos todas este esta estes estas esse essa
isso isto aquele aquela seu sua seus suas lhe lhes como mais menos muito também já não sim
""".split())


def _fts_query(q: str, match_any: bool = False) -> str:
    """Transforma o texto digitado em consulta FTS5 segura (termos entre aspas).

    Padrão: todos os termos (AND). `match_any`: qualquer termo relevante (OR), usado na
    pesquisa híbrida para frases inteiras; o BM25 prioriza trechos com mais termos em comum.
    """
    terms = re.findall(r"\w+", q, flags=re.UNICODE)
    if not match_any:
        return " ".join(f'"{t}"' for t in terms)
    useful = [t for t in terms if t.lower() not in STOPWORDS_PT and len(t) > 1] or terms
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(t.lower() for t in useful))


def search_text(q: str, limit: int = 20, unit: str = "", discipline: str = "",
                project: str = "", match_any: bool = False) -> list[dict]:
    """Busca por palavras exatas (FTS5). Também é a parte textual da pesquisa híbrida."""
    fq = _fts_query(q, match_any)
    if not fq:
        return []
    sql = """
        SELECT c.id AS chunk_id, c.document_id, d.title AS document_title, d.unit,
               d.discipline, c.section_path,
               snippet(chunks_fts, 0, '[', ']', ' … ', 24) AS snippet
        FROM chunks_fts
        JOIN chunks c ON c.id = chunks_fts.rowid
        JOIN documents d ON d.id = c.document_id
        WHERE chunks_fts MATCH ? AND d.deleted_at IS NULL
    """
    params: list = [fq]
    if unit:
        sql += " AND d.unit = ? COLLATE NOCASE"
        params.append(unit)
    if discipline:
        sql += " AND d.discipline = ? COLLATE NOCASE"
        params.append(discipline)
    if project:
        sql += " AND d.project = ? COLLATE NOCASE"
        params.append(project)
    sql += " ORDER BY bm25(chunks_fts) LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
