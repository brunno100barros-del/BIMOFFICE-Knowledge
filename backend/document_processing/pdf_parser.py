"""Leitura de memoriais em PDF (somente leitura), no MESMO formato do parser DOCX.

Resultado: ParsedDocument com blocos (parágrafos/títulos) e seções, para que o chunker,
os embeddings E5 e a pesquisa híbrida sejam exatamente os mesmos dos DOCX.

Como funciona (heurístico, declarado):
- Extrai o texto de cada página com pypdf (licença BSD, só Python).
- Remove cabeçalhos/rodapés repetidos e números de página.
- Junta as linhas quebradas pelo PDF em parágrafos e desfaz hifenização no fim da linha.
- Detecta títulos pela numeração ("1.2 Revestimentos") ou CAIXA ALTA, como no DOCX.

Limitações:
- PDF não guarda "parágrafos" nem "estilos": títulos e parágrafos são reconstruídos.
- Tabelas viram linhas de texto simples.
- PDF escaneado (imagem) não tem texto: é recusado com aviso. OCR pode ser ligado no
  futuro implementando `OcrProvider` (não há OCR nesta versão).
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Protocol

from backend.document_processing.docx_parser import (
    NO_SECTION, NUMBERED_HEADING, Block, ParsedDocument, Section,
)

PAGE_NUMBER = re.compile(
    r"^(p[áa]g(ina)?\.?\s*)?\d{1,4}(\s*(de|/)\s*\d{1,4})?$", re.IGNORECASE
)
SENTENCE_END = (".", ":", ";", "!", "?")
MIN_TEXT_CHARS = 40  # abaixo disso consideramos "sem texto extraível"


class PdfWithoutText(ValueError):
    """PDF sem camada de texto (provavelmente digitalizado)."""


class OcrProvider(Protocol):
    """Ponto de extensão para OCR futuro (ex.: Tesseract local). Não implementado."""

    def page_texts(self, path: Path) -> list[str]: ...


def _page_texts(path: Path) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise ValueError("PDF protegido por senha.")
        except Exception as e:
            raise ValueError("PDF protegido por senha; não é possível ler o texto.") from e
    texts = []
    for page in reader.pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception:  # página corrompida: segue com as demais
            texts.append("")
    return texts


def _clean_lines(pages: list[str]) -> list[list[str]]:
    """Linhas por página, sem cabeçalhos/rodapés repetidos e sem números de página."""
    pages_lines = [[" ".join(l.split()) for l in p.splitlines()] for p in pages]
    pages_lines = [[l for l in pl if l] for pl in pages_lines]
    # linha que aparece nas bordas (3 primeiras/3 últimas) de >= metade das páginas
    edge = Counter()
    for pl in pages_lines:
        for l in set(pl[:3] + pl[-3:]):
            edge[l] += 1
    threshold = max(2, (len(pages_lines) + 1) // 2)
    repeated = {l for l, n in edge.items() if n >= threshold} if len(pages_lines) >= 3 else set()
    return [
        [l for l in pl if l not in repeated and not PAGE_NUMBER.match(l)]
        for pl in pages_lines
    ]


def _heading_level(line: str) -> int | None:
    if len(line) > 150 or line.endswith(SENTENCE_END):
        return None
    m = NUMBERED_HEADING.match(line)
    if m and m.group(2)[0].isupper():
        return m.group(1).count(".") + 1
    letters = [c for c in line if c.isalpha()]
    if 3 <= len(line) <= 100 and len(letters) >= 3 and line.isupper() and len(line.split()) <= 12:
        return 1
    return None


def parse_pdf(path: Path) -> ParsedDocument:
    pages = _clean_lines(_page_texts(path))
    if sum(len(l) for pl in pages for l in pl) < MIN_TEXT_CHARS:
        raise PdfWithoutText(
            "O PDF não possui texto extraível (provavelmente é digitalizado/escaneado). "
            "OCR ainda não está disponível nesta versão."
        )

    result = ParsedDocument()
    stack: list[tuple[int, str]] = []
    current_path, current_section = NO_SECTION, None
    idx = 0
    para: list[str] = []
    para_page = 1

    def flush():
        nonlocal para, idx
        if para:
            text = " ".join(para)
            result.blocks.append(
                Block(idx, "paragraph", text, current_path, current_section, page=para_page)
            )
            idx += 1
            para = []

    for page_no, lines in enumerate(pages, 1):
        for line in lines:
            level = _heading_level(line)
            if level is not None:
                flush()
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, line))
                current_path = " > ".join(t for _, t in stack)
                result.sections.append(Section(level, line, current_path, idx))
                current_section = len(result.sections) - 1
                result.blocks.append(
                    Block(idx, "heading", line, current_path, current_section, page=page_no)
                )
                idx += 1
                continue
            if not para:
                para_page = page_no
            if para and para[-1].endswith("-") and line[:1].islower():
                para[-1] = para[-1][:-1] + line  # desfaz hifenização "revesti-\nmento"
            else:
                para.append(line)
            if line.endswith(SENTENCE_END):
                flush()
        # parágrafo pode continuar na próxima página (não fecha aqui)
    flush()
    return result
