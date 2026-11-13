from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: int
    title: str
    unit: str
    project: str
    discipline: str
    doc_date: str
    description: str
    tags: list[str]
    original_filename: str
    sha256: str
    n_sections: int
    n_chunks: int
    created_at: str
    indexed_at: str | None = None
    deleted_at: str | None = None


class SectionOut(BaseModel):
    id: int
    level: int
    title: str
    path: str
    position: int


class ChunkOut(BaseModel):
    id: int
    section_path: str
    position_start: int
    position_end: int
    est_page: int | None = Field(
        None, description="Página ESTIMADA; o DOCX não armazena paginação."
    )
    text: str


class TextHit(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    unit: str
    discipline: str
    section_path: str
    snippet: str


class DocumentUpdate(BaseModel):
    """Campos editáveis dos metadados (todos opcionais). Hash, arquivo e id não são editáveis."""
    model_config = {"extra": "forbid"}

    title: str | None = None
    unit: str | None = None
    project: str | None = None
    discipline: str | None = None
    doc_date: str | None = None
    description: str | None = None
    tags: str | list[str] | None = Field(None, description="Lista ou texto separado por vírgula")


# ------------------------------------------------------------------ Etapa 2: pesquisa
class SearchResult(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    unit: str
    project: str
    discipline: str
    section_path: str
    est_page: int | None = Field(None, description="Página ESTIMADA.")
    text: str
    relative_relevance: int = Field(
        ..., description="Relevância RELATIVA (0–100): 100 = 1º lugar em todas as buscas "
                         "usadas; achado por só uma busca ≤ ~50. NÃO é probabilidade nem "
                         "equivalência técnica.")
    found_by: list[str] = Field(..., description="Quais buscas encontraram: semântica e/ou textual")
    semantic_rank: int | None = None
    semantic_similarity: float | None = Field(None, description="Cosseno entre vetores (técnico)")
    text_rank: int | None = None
    snippet: str | None = None


class SearchResponse(BaseModel):
    query: str
    mode: str
    semantic_used: bool
    model: str | None
    warnings: list[str]
    results: list[SearchResult]
