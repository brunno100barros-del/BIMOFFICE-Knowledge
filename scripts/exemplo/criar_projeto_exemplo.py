"""Monta o PROJETO EXEMPLO dentro do BIMOFFICE Knowledge (no seu computador).

1. Importa os 3 memoriais de referência de exemplo na BIBLIOTECA (e gera os vetores, se o modelo E5 existir).
2. Cria o projeto "Escola SENAI - Bloco B (EXEMPLO)" e envia o IFC modelo.
3. Lê o IFC (inventário) e gera o MEMORIAL por capítulos, com sugestões da biblioteca.

Uso (com o servidor DESLIGADO ou ligado, tanto faz):
    python scripts/exemplo/criar_projeto_exemplo.py
Depois abra http://127.0.0.1:8000/#/memoriais

Os dados são de EXEMPLO (fictícios). Para removê-los, exclua o projeto e os documentos pela interface.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend import config, jobs  # noqa: E402
from backend.database.db import init_db  # noqa: E402
from backend.memorials import service as memorials  # noqa: E402
from backend.projects import service as projects  # noqa: E402
from backend.semantic_search import vector_store  # noqa: E402
from backend.services import library_service as lib  # noqa: E402

IFC = ROOT / "exemplos" / "projeto_exemplo" / "Escola_SENAI_Bloco_B_EXEMPLO.ifc"
REFS = {
    "Referencia_Arquitetura_e_Acabamentos_EXEMPLO.docx": "Arquitetura",
    "Referencia_Estrutura_e_Fundacoes_EXEMPLO.docx": "Estrutura",
    "Referencia_Instalacoes_EXEMPLO.docx": "Instalações",
}
NOME = "Escola SENAI - Bloco B (EXEMPLO)"


def main() -> dict:
    config.ensure_dirs()
    init_db()
    print("1) Biblioteca: memoriais de referência de exemplo")
    for fname, disc in REFS.items():
        path = ROOT / "exemplos" / "memoriais_referencia" / fname
        try:
            d = lib.import_document(fname, path.read_bytes(), {
                "title": path.stem.replace("_", " "), "unit": "SENAI (exemplo)", "discipline": disc,
                "description": "Memorial de referência FICTÍCIO para demonstração", "tags": "exemplo"})
            print(f"   importado: {d['title']} ({d['n_sections']} seções, {d['n_chunks']} trechos)")
        except lib.DuplicateDocument as e:
            print(f"   já estava na biblioteca: {fname} (id {e.existing_id})")
    try:
        r = vector_store.index_pending()
        print(f"   vetores gerados: {r['indexed']} (modelo {r['model']})")
    except Exception as e:  # sem modelo E5: as sugestões usam só a busca por palavras
        print(f"   AVISO: pesquisa semântica indisponível ({e}). Sugestões usarão só a busca por palavras.")

    print("2) Projeto e modelo IFC")
    existing = [p for p in projects.list_projects() if p["name"] == NOME]
    p = existing[0] if existing else projects.create_project(
        NOME, "Projeto FICTÍCIO para demonstração do BIMOFFICE Knowledge", "Porto Velho/RO (exemplo)",
        ["Arquitetura", "Estrutura", "Instalações"])
    try:
        with open(IFC, "rb") as fh:
            f, job = projects.store_file(p["id"], IFC.name, fh, "Multidisciplinar")
        print(f"   IFC enviado (tarefa {job['id']}); processando…")
        jobs.run_pending()
        f = projects.get_file(f["id"])
        print(f"   situação: {f['status']} · {f['ifc_model']['n_elements'] if f['ifc_model'] else 0} elementos")
    except projects.Duplicate:
        print("   o IFC de exemplo já estava no projeto")

    print("3) Memorial descritivo (minuta, por capítulos)")
    m = memorials.create_memorial(p["id"], title="Memorial descritivo — Escola SENAI Bloco B (EXEMPLO)")
    print(f"   memorial {m['id']} com {len(m['chapters'])} capítulos:")
    for c in m["chapters"]:
        print(f"    - {c['title']}: {len(c['facts'])} dado(s) do IFC, {len(c['pending'])} pendência(s), "
              f"{len(c['suggestions'])} sugestão(ões) da biblioteca")
    print(f"\nPronto. Abra: http://127.0.0.1:8000/#/memorial/{m['id']}")
    return m


if __name__ == "__main__":
    main()
