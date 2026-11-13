"""Mostra as seções e os trechos detectados nos DOCX da pasta amostras/.

Somente leitura: não altera os arquivos nem grava nada no banco.
Uso:  python scripts/inspecionar_amostras.py [pasta]   (padrão: amostras/)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.document_processing.chunker import chunk_document  # noqa: E402
from backend.document_processing.docx_parser import parse_docx  # noqa: E402


def inspecionar(path: Path) -> None:
    print("=" * 100)
    print(f"ARQUIVO: {path.name}")
    parsed = parse_docx(path)
    chunks = chunk_document(parsed)
    n_tab = sum(1 for b in parsed.blocks if b.kind == "table")
    print(f"Blocos: {len(parsed.blocks)} | Tabelas: {n_tab} | Seções: {len(parsed.sections)} "
          f"| Trechos: {len(chunks)}")
    print("\n--- SEÇÕES DETECTADAS (nível | título) ---")
    for s in parsed.sections:
        print(f"  {'  ' * (s.level - 1)}[{s.level}] {s.title[:90]}")
    sem = [b for b in parsed.blocks if b.section_index is None and b.kind != "heading"]
    if sem:
        print(f"\n!! {len(sem)} bloco(s) antes da primeira seção (sem seção)")
    print("\n--- TRECHOS (seção | tamanho | início do texto) ---")
    for i, c in enumerate(chunks, 1):
        txt = c.text.replace("\n", " ⏎ ")
        print(f"  #{i:03d} [{c.section_path[:60]}] ({len(c.text)} car., pág.≈{c.est_page})")
        print(f"        {txt[:160]}")
    tam = [len(c.text) for c in chunks]
    if tam:
        print(f"\nTamanho dos trechos: mín {min(tam)}, médio {sum(tam)//len(tam)}, máx {max(tam)}")


if __name__ == "__main__":
    pasta = Path(sys.argv[1] if len(sys.argv) > 1 else "amostras")
    arquivos = sorted(p for p in pasta.glob("*.docx") if not p.name.startswith("~$"))
    if not arquivos:
        print(f"Nenhum .docx encontrado em {pasta}/")
    for a in arquivos:
        try:
            inspecionar(a)
        except Exception as e:  # mostra o erro, não esconde
            print(f"ERRO ao ler {a.name}: {type(e).__name__}: {e}")
