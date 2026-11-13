"""Avalia a pesquisa híbrida com os memoriais reais da pasta amostras/.

Importa os DOCX numa pasta de dados TEMPORÁRIA (não toca na biblioteca real em data/),
gera os vetores com o modelo local e mostra os 5 melhores resultados de cada pergunta.

Uso:
    python scripts/avaliar_pesquisa.py                       (perguntas padrão)
    python scripts/avaliar_pesquisa.py "minha pergunta" ...  (suas perguntas)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BIMOFFICE_DATA_DIR"] = tempfile.mkdtemp(prefix="bimoffice_aval_")
os.environ.setdefault("HF_HUB_CACHE", str(ROOT / "data" / "embeddings" / "modelos"))

from backend import config  # noqa: E402
from backend.database.db import init_db  # noqa: E402
from backend.semantic_search import hybrid, vector_store  # noqa: E402
from backend.services import library_service as svc  # noqa: E402

config.MODELS_DIR = ROOT / "data" / "embeddings" / "modelos"  # reaproveita o modelo já baixado

PADRAO = [
    "revestimento cerâmico nas paredes dos sanitários",
    "impermeabilização de lajes e áreas molhadas",
    "pintura das paredes internas",
    "instalações elétricas e quadros de distribuição",
    "cobertura e telhado",
    "esquadrias de alumínio e vidro",
]


def main() -> None:
    config.ensure_dirs()
    init_db()
    arquivos = sorted(p for p in (ROOT / "amostras").glob("*.docx") if not p.name.startswith("~$"))
    if not arquivos:
        print("Nenhum .docx em amostras/. Coloque 2 ou 3 memoriais reais lá.")
        return
    for a in arquivos:
        d = svc.import_document(a.name, a.read_bytes(), {"title": a.stem})
        print(f"Importado: {a.name} -> {d['n_sections']} seções, {d['n_chunks']} trechos")
    print("Gerando vetores (a primeira vez demora)...")
    print(vector_store.index_pending())
    for q in sys.argv[1:] or PADRAO:
        res = hybrid.search(q, limit=5)
        print("\n" + "=" * 100 + f"\nPERGUNTA: {q}")
        for w in res["warnings"]:
            print(f"  AVISO: {w}")
        for i, r in enumerate(res["results"], 1):
            sim = r["semantic_similarity"]
            print(f"  {i}. relevância relativa {r['relative_relevance']:>3}% | encontrado por: "
                  f"{' + '.join(r['found_by'])} | cosseno {sim if sim is not None else '-'}")
            print(f"     ORIGEM: {r['document_title']} › {r['section_path']} (pág.≈{r['est_page']})")
            print(f"     {r['text'].replace(chr(10), ' ⏎ ')[:220]}")


if __name__ == "__main__":
    main()
