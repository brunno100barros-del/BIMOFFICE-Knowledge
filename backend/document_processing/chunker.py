"""Divide o documento em trechos coerentes, respeitando as seções.

Regras:
- Nunca mistura texto de seções diferentes no mesmo trecho.
- Junta parágrafos consecutivos até ~CHUNK_TARGET_CHARS.
- Parágrafos/tabelas maiores que CHUNK_MAX_CHARS são divididos em linhas/frases.
- Trecho final muito curto é unido ao anterior da mesma seção.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend import config
from backend.document_processing.docx_parser import ParsedDocument

# ~3000 caracteres por página A4 de texto corrido (estimativa grosseira)
CHARS_PER_PAGE = 3000


@dataclass
class Chunk:
    section_index: int | None
    section_path: str
    position_start: int
    position_end: int
    est_page: int
    text: str


def _split_long(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts = re.split(r"(?<=[\.\!\?;])\s+|\n", text)
    out, buf = [], ""
    for part in parts:
        if len(part) > max_chars:  # frase gigante: corte duro
            if buf:
                out.append(buf)
                buf = ""
            out.extend(part[i : i + max_chars] for i in range(0, len(part), max_chars))
            continue
        if buf and len(buf) + len(part) + 1 > max_chars:
            out.append(buf)
            buf = part
        else:
            buf = f"{buf}\n{part}" if buf else part
    if buf:
        out.append(buf)
    return out


def chunk_document(parsed: ParsedDocument) -> list[Chunk]:
    target, maxc, minc = (
        config.CHUNK_TARGET_CHARS,
        config.CHUNK_MAX_CHARS,
        config.CHUNK_MIN_CHARS,
    )
    chunks: list[Chunk] = []
    chars_so_far = 0

    # agrupa blocos por seção, preservando a ordem
    groups: list[list] = []
    for b in parsed.blocks:
        if groups and groups[-1][0].section_index == b.section_index:
            groups[-1].append(b)
        else:
            groups.append([b])

    for group in groups:
        section_index, path = group[0].section_index, group[0].section_path
        cur: list[tuple[int, str]] = []  # (posição, texto)
        cur_len = 0
        has_body = False  # o trecho atual tem conteúdo além de títulos?
        cur_page: int | None = None  # página real do 1º bloco (PDF)
        built: list[Chunk] = []

        def flush():
            nonlocal cur, cur_len, chars_so_far, has_body, cur_page
            if not cur or not has_body:
                # trecho só com título(s): sem conteúdo útil, não vira trecho
                cur, cur_len, cur_page = [], 0, None
                return
            text = "\n".join(t for _, t in cur)
            built.append(
                Chunk(
                    section_index, path, cur[0][0], cur[-1][0],
                    cur_page or chars_so_far // CHARS_PER_PAGE + 1, text,
                )
            )
            chars_so_far += len(text)
            cur, cur_len, has_body, cur_page = [], 0, False, None

        for b in group:
            if not cur:
                cur_page = b.page
            if b.kind == "heading":
                # o título fica no trecho para dar contexto
                cur.append((b.index, b.text))
                cur_len += len(b.text)
                continue
            for piece in _split_long(b.text, maxc):
                if cur and cur_len + len(piece) > target:
                    flush()
                if not cur:
                    cur_page = b.page
                cur.append((b.index, piece))
                cur_len += len(piece)
                has_body = True
        flush()

        # une trecho final muito curto ao anterior (da mesma seção)
        if len(built) > 1 and len(built[-1].text) < minc:
            last = built.pop()
            prev = built[-1]
            if len(prev.text) + len(last.text) <= maxc * 1.25:
                prev.text += "\n" + last.text
                prev.position_end = last.position_end
            else:
                built.append(last)
        chunks.extend(built)

    return [c for c in chunks if c.text.strip()]
