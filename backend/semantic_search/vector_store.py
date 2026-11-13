"""Armazenamento dos vetores no SQLite (coluna BLOB de `chunks`) e busca vetorial com numpy.

Camada pensada para ser substituída por FAISS/Qdrant se a biblioteca crescer muito.
"""
from __future__ import annotations

import logging

import numpy as np

from backend import config
from backend.database.db import get_conn
from backend.semantic_search.providers import get_provider

log = logging.getLogger("bimoffice.vector_store")


def _to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def _from_blob(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def index_pending(document_id: int | None = None, force: bool = False) -> dict:
    """Gera vetores dos trechos sem vetor (ou de outro modelo). `force` refaz todos.

    Lança EmbeddingUnavailable se o modelo não puder ser carregado.
    """
    provider = get_provider()
    sql = """SELECT c.id, c.text FROM chunks c JOIN documents d ON d.id = c.document_id
             WHERE d.deleted_at IS NULL"""
    params: list = []
    if not force:
        sql += " AND (c.embedding IS NULL OR c.embedding_model IS NOT ?)"
        params.append(provider.name)
    if document_id is not None:
        sql += " AND c.document_id = ?"
        params.append(document_id)
    with get_conn() as conn:
        rows = conn.execute(sql + " ORDER BY c.id", params).fetchall()
    done = 0
    step = max(config.EMBEDDING_BATCH_SIZE * 4, 1)
    for i in range(0, len(rows), step):
        batch = rows[i : i + step]
        vecs = provider.embed_passages([r["text"] for r in batch])
        with get_conn() as conn:
            conn.executemany(
                "UPDATE chunks SET embedding=?, embedding_model=? WHERE id=?",
                [(_to_blob(v), provider.name, r["id"]) for v, r in zip(vecs, batch)],
            )
        done += len(batch)
    if done:
        log.info("Vetores gerados para %s trecho(s) (modelo %s)", done, provider.name)
    return {"indexed": done, "model": provider.name}


def status(model_name: str) -> dict:
    with get_conn() as conn:
        r = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN c.embedding IS NOT NULL AND c.embedding_model = ? THEN 1 ELSE 0 END) AS ok
               FROM chunks c JOIN documents d ON d.id = c.document_id
               WHERE d.deleted_at IS NULL""",
            (model_name,),
        ).fetchone()
    total, ok = r["total"] or 0, r["ok"] or 0
    return {"chunks_total": total, "chunks_indexed": ok, "chunks_pending": total - ok}


def _filters_sql(unit: str, discipline: str, project: str) -> tuple[str, list]:
    sql, params = "", []
    for col, val in (("unit", unit), ("discipline", discipline), ("project", project)):
        if val:
            sql += f" AND d.{col} = ? COLLATE NOCASE"
            params.append(val)
    return sql, params


def vector_search(query_vec: np.ndarray, model_name: str, limit: int,
                  unit: str = "", discipline: str = "", project: str = "") -> list[tuple[int, float]]:
    """Retorna [(chunk_id, similaridade_cosseno)] dos trechos mais próximos."""
    fsql, fparams = _filters_sql(unit, discipline, project)
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT c.id, c.embedding FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE d.deleted_at IS NULL AND c.embedding IS NOT NULL
                  AND c.embedding_model = ? {fsql}""",
            [model_name, *fparams],
        ).fetchall()
    if not rows:
        return []
    ids = np.fromiter((r["id"] for r in rows), dtype=np.int64, count=len(rows))
    matrix = np.vstack([_from_blob(r["embedding"]) for r in rows])
    scores = matrix @ np.asarray(query_vec, dtype=np.float32)
    k = min(limit, len(scores))
    top = np.argpartition(-scores, k - 1)[:k]
    top = top[np.argsort(-scores[top])]
    return [(int(ids[i]), float(scores[i])) for i in top]
