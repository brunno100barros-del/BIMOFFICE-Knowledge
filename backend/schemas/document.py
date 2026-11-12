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
