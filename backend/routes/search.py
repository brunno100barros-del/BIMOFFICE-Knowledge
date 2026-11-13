from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.schemas.document import SearchResponse
from backend.semantic_search import hybrid, vector_store
from backend.semantic_search.providers import EmbeddingUnavailable, get_provider

router = APIRouter(prefix="/api/search", tags=["pesquisa inteligente"])


@router.get("", response_model=SearchResponse)
def search(
    q: str,
    limit: int = Query(20, ge=1, le=100),
    mode: str = Query("hybrid", description="hybrid (padrão) | semantic | text"),
    unit: str = "", discipline: str = "", project: str = "",
):
    """Pesquisa híbrida (significado + palavras). Os resultados são trechos da biblioteca
    com a origem (documento, unidade, obra, seção). Similaridade não é equivalência técnica."""
    try:
        return hybrid.search(q, limit, mode, unit, discipline, project)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/status")
def status():
    """Situação da indexação vetorial (trechos com e sem vetor)."""
    p = get_provider()
    return {"model": p.name, **vector_store.status(p.name)}


@router.post("/reindex")
def reindex(force: bool = False, document_id: int | None = None):
    """Gera os vetores dos trechos pendentes. `force=true` refaz todos (ex.: após trocar o modelo).
    A primeira execução pode demorar (download e carga do modelo)."""
    try:
        r = vector_store.index_pending(document_id, force)
    except EmbeddingUnavailable as e:
        raise HTTPException(503, f"Modelo de embeddings indisponível: {e}")
    return {**r, **vector_store.status(r["model"])}
