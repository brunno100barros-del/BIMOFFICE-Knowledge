"""Gera a DEMONSTRAÇÃO ESTÁTICA (somente leitura) para o GitHub Pages.

Roda o sistema DE VERDADE (numa pasta temporária) com o projeto exemplo e grava as respostas
reais da API em frontend/demo/. Nada é inventado: são exatamente os dados que o backend produziu.

Passos: importa os 3 memoriais de referência -> gera vetores (modelo E5, se disponível) ->
cria o projeto -> lê o IFC -> gera o memorial -> insere a referência do assunto de cada capítulo
(somente se o próprio sistema a SUGERIU) -> exporta a minuta DOCX -> grava os JSON.

Uso: python scripts/exemplo/gerar_demo_estatico.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "frontend" / "demo"
TMP = Path(tempfile.mkdtemp(prefix="bimoffice_demo_"))
os.environ["BIMOFFICE_DATA_DIR"] = str(TMP)
os.environ["BIMOFFICE_JOB_WORKER"] = "0"
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend import config, jobs  # noqa: E402
from backend.main import app  # noqa: E402

config.MODELS_DIR = ROOT / "data" / "embeddings" / "modelos"  # reaproveita o modelo E5 já baixado

IFC = ROOT / "exemplos" / "projeto_exemplo" / "Escola_SENAI_Bloco_B_EXEMPLO.ifc"
REFS = sorted((ROOT / "exemplos" / "memoriais_referencia").glob("*.docx"))
DISC = {"Arquitetura": "Arquitetura", "Estrutura": "Estrutura", "Instalacoes": "Instalações"}
# capítulo -> seção de referência que o engenheiro escolheria (inserida SÓ se o sistema sugerir)
ESCOLHA = {
    "apresentacao": "1 DISPOSIÇÕES GERAIS", "servicos_preliminares": "2 SERVIÇOS PRELIMINARES",
    "fundacoes": "2 FUNDAÇÕES", "estrutura": "3.2 Formas e armaduras",
    "estrutura_metalica": "4 ESTRUTURA METÁLICA DA COBERTURA", "vedacoes": "3.1 Alvenaria de blocos cerâmicos",
    "revestimentos": "4.2 Revestimento cerâmico em áreas molhadas", "pisos": "5.2 Porcelanato nas salas de aula",
    "forros": "6 FORROS", "pintura": "8 PINTURA", "esquadrias": "7.2 Esquadrias de alumínio",
    "escadas": "5 ESCADAS E GUARDA-CORPOS", "cobertura": "9 COBERTURA",
    "hidro": "1 INSTALAÇÕES DE ÁGUA FRIA", "eletrica": "5 INSTALAÇÕES ELÉTRICAS",
    "climatizacao": "7 CLIMATIZAÇÃO E EXAUSTÃO", "limpeza": "10 LIMPEZA FINAL",
}


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "files").mkdir(parents=True)
    manifest: dict[str, str] = {}

    with TestClient(app) as c:
        def ok(r, code=200):
            assert r.status_code == code, (r.status_code, r.text[:300])
            return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else r

        def save(path: str, data, name: str | None = None) -> None:
            name = name or path.strip("/").replace("api/", "").replace("/", "_") + ".json"
            (OUT / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            manifest[path] = name

        # 1) biblioteca
        for r in REFS:
            disc = next((v for k, v in DISC.items() if k in r.name), "")
            with open(r, "rb") as fh:
                ok(c.post("/api/library/documents", files={"file": (r.name, fh)},
                          data={"title": r.stem.replace("_", " "), "unit": "SENAI (exemplo)", "discipline": disc,
                                "tags": "exemplo, referência"}), 201)
        print("vetores:", ok(c.post("/api/search/reindex")))
        # 2) projeto + IFC
        p = ok(c.post("/api/projects", json={"name": "Escola SENAI - Bloco B (EXEMPLO)",
                                             "location": "Porto Velho/RO (exemplo)",
                                             "description": "Projeto fictício para demonstração"}), 201)
        pid = p["id"]
        with open(IFC, "rb") as fh:
            ok(c.post(f"/api/projects/{pid}/files", files={"file": (IFC.name, fh)},
                      data={"discipline": "Multidisciplinar"}), 201)
        jobs.run_pending()
        # 3) memorial + inserções escolhidas entre as SUGESTÕES do sistema
        m = ok(c.post(f"/api/projects/{pid}/memorials", json={}), 201)
        inserted = []
        for ch in m["chapters"]:
            want = ESCOLHA.get(ch["key"])
            s = next((s for s in ch["suggestions"] if want and s["section_path"].endswith(want)), None)
            if s:
                ok(c.post(f"/api/memorial-chapters/{ch['id']}/insert-reference", params={"chunk_id": s["chunk_id"]}))
                inserted.append(ch["title"])
        print(f"referências inseridas (sugeridas pelo sistema): {len(inserted)}")
        mid = m["id"]

        # 4) gravar respostas reais
        cfg = ok(c.get("/api/config"))
        cfg["demo"] = True
        save("/api/config", cfg)
        save("/api/library/stats", ok(c.get("/api/library/stats")))
        save("/api/search/status", ok(c.get("/api/search/status")))
        docs = ok(c.get("/api/library/documents"))
        save("/api/library/documents", docs)
        for d in docs:
            for sub in ("", "/sections", "/chunks"):
                save(f"/api/library/documents/{d['id']}{sub}", ok(c.get(f"/api/library/documents/{d['id']}{sub}")))
            fname = f"files/biblioteca_{d['id']}.docx"
            (OUT / fname).write_bytes(c.get(f"/api/library/documents/{d['id']}/original").content)
            manifest[f"/api/library/documents/{d['id']}/original"] = fname
        save("/api/projects", ok(c.get("/api/projects")))
        save(f"/api/projects/{pid}", ok(c.get(f"/api/projects/{pid}")))
        files = ok(c.get(f"/api/projects/{pid}/files"))
        save(f"/api/projects/{pid}/files", files)
        for f in files:
            fname = f"files/projeto_{f['id']}_{f['original_filename']}"
            (OUT / fname).write_bytes(c.get(f"/api/projects/{pid}/files/{f['id']}/original").content)
            manifest[f"/api/projects/{pid}/files/{f['id']}/original"] = fname
        save(f"/api/projects/{pid}/history", ok(c.get(f"/api/projects/{pid}/history")))
        models = ok(c.get(f"/api/projects/{pid}/ifc-models"))
        save(f"/api/projects/{pid}/ifc-models", models)
        save(f"/api/projects/{pid}/memorials", ok(c.get(f"/api/projects/{pid}/memorials")))
        save("/api/memorials", ok(c.get("/api/memorials")))
        mem = ok(c.get(f"/api/memorials/{mid}"))
        save(f"/api/memorials/{mid}", mem)
        save("/api/jobs", [])
        for ch in mem["chapters"]:
            save(f"/api/memorial-chapters/{ch['id']}/history", ok(c.get(f"/api/memorial-chapters/{ch['id']}/history")))
        r = c.get(f"/api/memorials/{mid}/export", params={"draft": True})
        assert r.status_code == 200
        (OUT / "files" / "memorial_minuta.docx").write_bytes(r.content)
        manifest[f"/api/memorials/{mid}/export?draft=true"] = "files/memorial_minuta.docx"
        for mo in models:
            save(f"/api/ifc-models/{mo['id']}", ok(c.get(f"/api/ifc-models/{mo['id']}")))
            allel = ok(c.get(f"/api/ifc-models/{mo['id']}/elements", params={"limit": 1000}))
            save(f"/api/ifc-models/{mo['id']}/elements", allel)
            details = {str(e["id"]): ok(c.get(f"/api/ifc-elements/{e['id']}")) for e in allel["items"]}
            (OUT / f"elementos_{mo['id']}.json").write_text(json.dumps(details, ensure_ascii=False), encoding="utf-8")
            manifest[f"elements_detail:{mo['id']}"] = f"elementos_{mo['id']}.json"
            save(f"/api/ifc-models/{mo['id']}/export", ok(c.get(f"/api/ifc-models/{mo['id']}/export")))

    (OUT / "manifest.json").write_text(json.dumps({
        "about": "Respostas REAIS da API do BIMOFFICE Knowledge para o projeto exemplo (dados fictícios). "
                 "Geradas por scripts/exemplo/gerar_demo_estatico.py. Somente leitura.",
        "routes": manifest}, ensure_ascii=False, indent=1), encoding="utf-8")
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"demonstração gravada em {OUT} ({len(manifest)} rotas, {size / 1024:.0f} KB)")
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
