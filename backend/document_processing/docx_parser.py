"""Leitura de memoriais DOCX: blocos (parágrafos/tabelas) e hierarquia de títulos.

O arquivo original NUNCA é modificado: é aberto somente para leitura.

Limitações conhecidas (declaradas, não escondidas):
- A numeração automática do Word ("1.1", "1.2" geradas por lista) não aparece no
  texto lido pelo python-docx; títulos com estilo "Título N" são detectados pelo
  estilo, e títulos digitados à mão pela numeração/caixa alta (heurística).
- Cabeçalhos, rodapés, caixas de texto e notas de rodapé não são indexados.
- O DOCX não armazena números de página; a página é apenas ESTIMADA.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

NUMBERED_HEADING = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,4})[\.\)]?\s+(\S.{0,140})$")
STYLE_LEVEL = re.compile(r"^(?:heading|t[ií]tulo)\s*(\d)$", re.IGNORECASE)
NO_SECTION = "Início do documento"


@dataclass
class Block:
    index: int            # posição do bloco no documento original
    kind: str             # "paragraph" | "table" | "heading"
    text: str
    section_path: str
    section_index: int | None = None  # índice em ParsedDocument.sections
    page: int | None = None           # página REAL (PDF); DOCX não tem (None)


@dataclass
class Section:
    level: int
    title: str
    path: str
    position: int


@dataclass
class ParsedDocument:
    blocks: list[Block] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)


def _iter_blocks(doc):
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, doc)
        elif tag == "tbl":
            yield Table(child, doc)


def _style_name(p: Paragraph) -> str:
    try:
        return p.style.name or ""
    except Exception:  # estilo ausente/corrompido
        return ""


def _table_text(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells, seen = [], set()
        for cell in row.cells:
            if id(cell._tc) in seen:  # células mescladas repetem
                continue
            seen.add(id(cell._tc))
            t = " ".join(cell.text.split())
            cells.append(t)
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _heading_level(p: Paragraph, text: str) -> int | None:
    """Retorna o nível do título (1..9) ou None se for parágrafo comum."""
    m = STYLE_LEVEL.match(_style_name(p).strip())
    if m:
        return max(1, int(m.group(1)))
    if len(text) > 150 or text.endswith((".", ";", ":")):
        return None
    m = NUMBERED_HEADING.match(text)
    if m and m.group(2)[0].isupper():
        return m.group(1).count(".") + 1
    letters = [c for c in text if c.isalpha()]
    if (
        3 <= len(text) <= 100
        and len(letters) >= 3
        and text.isupper()
        and len(text.split()) <= 12
    ):
        return 1
    return None


def parse_docx(path: Path) -> ParsedDocument:
    doc = Document(str(path))
    result = ParsedDocument()
    stack: list[tuple[int, str]] = []  # (nível, título)
    current_path, current_section = NO_SECTION, None

    for idx, item in enumerate(_iter_blocks(doc)):
        if isinstance(item, Table):
            text = _table_text(item)
            if text.strip():
                result.blocks.append(
                    Block(idx, "table", text, current_path, current_section)
                )
            continue

        text = " ".join(item.text.split())
        if not text:
            continue
        level = _heading_level(item, text)
        if level is not None:
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
            current_path = " > ".join(t for _, t in stack)
            result.sections.append(Section(level, text, current_path, idx))
            current_section = len(result.sections) - 1
            result.blocks.append(Block(idx, "heading", text, current_path, current_section))
        else:
            result.blocks.append(
                Block(idx, "paragraph", text, current_path, current_section)
            )
    return result
