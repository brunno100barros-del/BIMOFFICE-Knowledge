"""Pesquisa híbrida: semântica (vetores) + textual (FTS5), unidas por RRF.

RRF (Reciprocal Rank Fusion): cada busca dá uma posição a cada trecho; a nota final é
a soma de 1/(k + posição). Trechos bem colocados nas duas buscas sobem.

A "relevância relativa" (0–100) é a nota RRF dividida pela maior nota possível nesta
pesquisa: 100 = 1º lugar em TODAS as buscas usadas (semântica e textual concordam).
Um trecho achado só por uma das buscas fica com no máximo ~50 na pesquisa híbrida.
Não é probabilidade nem equivalência técnica.
"""
from __future__ import annotations

import logging

from backend import config
from backend.database.db import get_conn
from backend.semantic_search import vector_store
from backend.semantic_search.providers import EmbeddingUnavailable, get_provider
from backend.services import library_service as lib

log = logging.getLogger("bimoffice.hybrid")

MODES = ("hybrid", "semantic", "text")


def _fetch_chunks(ids: list[int]) -> dict[int, dict]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT c.id AS chunk_id, c.document_id, d.title AS document_title,
                       d.original_filename, d.file_type, d.unit,
                       d.project, d.discipline, c.section_path, c.est_page, c.text
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE c.id IN ({marks})""",
            ids,
        ).fetchall()
    return {r["chunk_id"]: dict(r) for r in rows}


def search(q: str, limit: int = 20, mode: str = "hybrid", unit: str = "",
           discipline: str = "", project: str = "") -> dict:
    if mode not in MODES:
        raise ValueError(f"Modo inválido: {mode}. Use {', '.join(MODES)}.")
    q = (q or "").strip()
    warnings: list[str] = []
    out = {"query": q, "mode": mode, "semantic_used": False, "model": None,
           "warnings": warnings, "results": []}
    if not q:
        return out

    n = max(config.HYBRID_CANDIDATES, limit)
    sem: list[tuple[int, float]] = []
    txt: list[dict] = []

    if mode in ("hybrid", "semantic"):
        provider = get_provider()
        try:
            st = vector_store.status(provider.name)
            if st["chunks_pending"]:
                warnings.append(
                    f"{st['chunks_pending']} trecho(s) ainda sem vetor; use "
                    "POST /api/search/reindex para incluí-los na pesquisa semântica."
                )
            qv = provider.embed_query(q)
            sem = vector_store.vector_search(qv, provider.name, n, unit, discipline, project)
            out["semantic_used"], out["model"] = True, provider.name
        except EmbeddingUnavailable as e:
            log.warning("Pesquisa semântica indisponível: %s", e)
            warnings.append(f"Pesquisa semântica INDISPONÍVEL ({e}).")
            if mode == "semantic":
                return out
            warnings.append("Resultados abaixo vêm SOMENTE da busca por palavras.")

    if mode in ("hybrid", "text"):
        txt = lib.search_text(q, n, unit, discipline, project, match_any=True)

    fused: dict[int, dict] = {}
    for rank, (cid, cos) in enumerate(sem, 1):
        e = fused.setdefault(cid, {"rrf": 0.0})
        e["rrf"] += 1.0 / (config.RRF_K + rank)
        e["semantic_rank"], e["semantic_similarity"] = rank, round(cos, 4)
    for rank, hit in enumerate(txt, 1):
        e = fused.setdefault(hit["chunk_id"], {"rrf": 0.0})
        e["rrf"] += 1.0 / (config.RRF_K + rank)
        e["text_rank"], e["snippet"] = rank, hit["snippet"]

    ranked = sorted(fused.items(), key=lambda kv: -kv[1]["rrf"])[:limit]
    info = _fetch_chunks([cid for cid, _ in ranked])
    n_lists = int(out["semantic_used"]) + int(mode in ("hybrid", "text"))
    best = max(n_lists, 1) / (config.RRF_K + 1)  # nota máxima possível
    for cid, e in ranked:
        if cid not in info:
            continue
        found_by = [n for n, k in (("semântica", "semantic_rank"), ("textual", "text_rank")) if k in e]
        out["results"].append({
            **info[cid],
            "relative_relevance": min(100, round(100 * e["rrf"] / best)),
            "found_by": found_by,
            "semantic_rank": e.get("semantic_rank"),
            "semantic_similarity": e.get("semantic_similarity"),
            "text_rank": e.get("text_rank"),
            "snippet": e.get("snippet"),
        })
    return out


def index_after_change(document_id: int) -> None:
    """Gera vetores de um documento recém-importado/reindexado, sem quebrar a importação."""
    if not config.EMBED_ON_IMPORT:
        return
    try:
        vector_store.index_pending(document_id)
    except EmbeddingUnavailable as e:
        log.warning("Documento %s importado sem vetores: %s", document_id, e)
    except Exception:
        log.exception("Falha ao gerar vetores do documento %s", document_id)
