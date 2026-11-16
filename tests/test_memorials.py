"""Memorial em elaboração: geração por capítulos a partir do IFC, sugestões, edição e exportação DOCX."""
import io
import re
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

pytest.importorskip("ifcopenshell")

from backend import jobs  # noqa: E402
from backend.main import app  # noqa: E402
from backend.memorials import service as msvc  # noqa: E402
from backend.projects import service as psvc  # noqa: E402
from backend.semantic_search import vector_store  # noqa: E402
from backend.services import library_service as lib  # noqa: E402
from tests.ifc_factory import build_model  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EXEMPLO_IFC = ROOT / "exemplos" / "projeto_exemplo" / "Escola_SENAI_Bloco_B_EXEMPLO.ifc"
REFS = sorted((ROOT / "exemplos" / "memoriais_referencia").glob("*.docx"))


@pytest.fixture
def project_with_model(tmp_path):
    p = psvc.create_project("Bloco de Salas", location="Porto Velho/RO")
    f = build_model(tmp_path / "m.ifc", "IFC4")
    with open(f, "rb") as fh:
        psvc.store_file(p["id"], "Arquitetura.ifc", fh)
    jobs.run_pending()
    return p


@pytest.fixture
def library_refs():
    for r in REFS:
        lib.import_document(r.name, r.read_bytes(), {"title": r.stem, "unit": "Exemplo"})
    vector_store.index_pending()


def _ch(m, key):
    return next(c for c in m["chapters"] if c["key"] == key)


def test_generation_uses_only_ifc_facts(project_with_model):
    m = msvc.create_memorial(project_with_model["id"])
    keys = [c["key"] for c in m["chapters"]]
    assert keys[0] == "apresentacao" and keys[-1] == "pendencias"
    for k in ("fundacoes", "estrutura", "estrutura_metalica", "vedacoes", "esquadrias", "hidro", "eletrica", "climatizacao"):
        assert k in keys, k
    v = _ch(m, "vedacoes")
    assert "Alvenaria 14 cm" in v["text"] and "espessura total 14 cm" in v["text"]
    assert "comprimento total 10,00 m" in v["text"]                     # 2 paredes x 5 m (Qto)
    assert "área total de parede" in v["text"]
    assert v["generated_text"] == v["text"] and not v["edited"]
    assert any(f["metodo"].startswith("quantidade explícita") for f in v["facts"])
    # o que não existe vira pendência, não valor
    e = _ch(m, "estrutura")
    assert any("sem volume" in p for p in e["pending"])
    assert "fck" not in e["text"]                                         # resistência não inventada
    assert "Porto Velho/RO" in _ch(m, "apresentacao")["text"]
    pend = _ch(m, "pendencias")["tables"][0]["rows"]
    assert any("Ralo sifonado" in r[1] and "sugestão" in r[1] for r in pend)


def test_every_number_in_generated_text_exists_in_ifc(project_with_model):
    """Nenhum número inventado: cada número do texto gerado precisa vir do IFC — de um nome/material/
    propriedade do modelo, de uma quantidade (fatos registrados) ou de uma contagem de elementos."""
    import json
    from backend.database.db import get_conn
    m = msvc.create_memorial(project_with_model["id"])
    with get_conn() as conn:
        els = [json.loads(r["data"]) for r in conn.execute("SELECT data FROM ifc_elements")]
        model = psvc.get_model(m["model_id"])
    corpus = [json.dumps(e, ensure_ascii=False) for e in els] + [json.dumps(model["summary"], ensure_ascii=False),
                                                               json.dumps(model["header"], ensure_ascii=False),
                                                               model["original_filename"], model["schema_name"]]
    for c in m["chapters"]:
        corpus += [f"{f['valor']}" for f in c["facts"]] + [str(x) for t in c["tables"] for row in t["rows"] for x in row]
    blob = " ".join(corpus)
    for c in m["chapters"]:
        for n in re.findall(r"\d+(?:[.,]\d+)?", c["generated_text"]):
            is_count = n.isdigit() and int(n) <= len(els)
            assert is_count or n in blob or n.replace(",", ".") in blob, (c["key"], n)


def test_references_are_only_suggestions_until_inserted(project_with_model, library_refs):
    m = msvc.create_memorial(project_with_model["id"])
    v = _ch(m, "vedacoes")
    assert v["suggestions"], "deveria sugerir trechos da biblioteca"
    assert all("Referencia" in s["original_filename"] for s in v["suggestions"])
    assert v["text"] == v["generated_text"]                              # nada inserido sozinho
    alv = next(s for s in v["suggestions"] if "Alvenaria" in s["section_path"] or "alvenaria" in s["text"].lower())
    v2 = msvc.insert_reference(v["id"], alv["chunk_id"])
    assert v2["text"].startswith(v["generated_text"])                    # o texto do IFC continua
    assert len(v2["inserted_refs"]) == 1
    ref = v2["inserted_refs"][0]
    assert ref["original_text"] and ref["section_path"] == alv["section_path"]   # origem + original guardados
    assert ref["inserted_text"] in v2["text"]
    # adaptar o texto não altera o original guardado nem a biblioteca
    msvc.update_chapter(v["id"], text=v2["text"].replace("aproximadamente", "cerca de"))
    v3 = msvc.get_chapter(v["id"])
    assert v3["inserted_refs"][0]["original_text"] == ref["original_text"]
    assert lib.list_chunks(alv["document_id"])  # biblioteca intacta


def test_complementary_chapters_get_suggestions(project_with_model, library_refs):
    m = msvc.create_memorial(project_with_model["id"])
    p = _ch(m, "pintura")
    assert p["text"] == "" and p["pending"]
    assert any("PINTURA" in s["section_path"] for s in p["suggestions"])


def test_edit_approve_history_and_regenerate(project_with_model):
    m = msvc.create_memorial(project_with_model["id"])
    c = _ch(m, "fundacoes")
    msvc.set_status(c["id"], True)
    assert msvc.get_chapter(c["id"])["status"] == "aprovado"
    c2 = msvc.update_chapter(c["id"], text=c["text"] + "\n\nTexto adicional do engenheiro.")
    assert c2["status"] == "rascunho" and c2["edited"]                   # editar exige nova aprovação
    # regerar NÃO apaga o texto editado (a menos que o usuário peça)
    c3 = msvc.regenerate_chapter(c["id"])
    assert "Texto adicional do engenheiro." in c3["text"]
    c4 = msvc.regenerate_chapter(c["id"], replace_text=True)
    assert "Texto adicional" not in c4["text"]
    events = [h["event"] for h in msvc.chapter_history(c["id"])]
    assert events[-1] == "gerado a partir do IFC" and "editado pelo usuário" in events and "aprovado" in events


def test_chapter_organization(project_with_model):
    m = msvc.create_memorial(project_with_model["id"])
    first, second = m["chapters"][0]["id"], m["chapters"][1]["id"]
    m2 = msvc.move_chapter(second, -1)
    assert m2["chapters"][0]["id"] == second
    new = msvc.add_chapter(m["id"], "Acessibilidade", after_id=first)
    m3 = msvc.get_memorial(m["id"])
    assert m3["chapters"][[c["id"] for c in m3["chapters"]].index(first) + 1]["id"] == new["id"]
    m4 = msvc.delete_chapter(new["id"])
    assert new["id"] not in [c["id"] for c in m4["chapters"]]
    assert [c["position"] for c in m4["chapters"]] == list(range(len(m4["chapters"])))


def test_export_draft_and_final(project_with_model):
    m = msvc.create_memorial(project_with_model["id"])
    data, name = msvc.export_docx(m["id"], draft=True)
    assert name.endswith("MINUTA.docx")
    d = Document(io.BytesIO(data))
    texts = [p.text for p in d.paragraphs]
    assert "MINUTA" in d.sections[0].header.paragraphs[0].text
    assert any(t.startswith("1 APRESENTAÇÃO") for t in texts)
    full = "\n".join(texts)
    assert "Alvenaria 14 cm" in full
    assert "relev" not in full.lower() and "GlobalId" not in full          # sem dados internos
    tables = {t.rows[0].cells[0].text for t in d.tables}
    assert {"Pavimento", "Tipo", "Capítulo"} <= tables                      # ambientes, esquadrias, pendências
    with pytest.raises(msvc.NotApproved):
        msvc.export_docx(m["id"], draft=False)
    for c in m["chapters"]:
        msvc.set_status(c["id"], True)
    data, name = msvc.export_docx(m["id"], draft=False)
    d = Document(io.BytesIO(data))
    assert "MINUTA" not in d.sections[0].header.paragraphs[0].text and "MINUTA" not in name


def test_memorial_without_ifc_model():
    p = psvc.create_project("Só documentos")
    m = msvc.create_memorial(p["id"])
    assert [c["key"] for c in m["chapters"]][:2] == ["apresentacao", "servicos_preliminares"]
    assert m["model_id"] is None


def test_example_project_full_flow(library_refs):
    """Projeto exemplo do repositório: IFC modelo + memoriais de referência -> memorial."""
    p = psvc.create_project("Escola SENAI - Bloco B (exemplo)", location="Porto Velho/RO")
    with open(EXEMPLO_IFC, "rb") as fh:
        psvc.store_file(p["id"], EXEMPLO_IFC.name, fh)
    jobs.run_pending()
    m = msvc.create_memorial(p["id"])
    titles = [c["title"] for c in m["chapters"]]
    for t in ("Fundações", "Estrutura de concreto", "Estrutura metálica", "Alvenarias e vedações", "Pisos", "Forros",
              "Esquadrias", "Cobertura", "Instalações hidrossanitárias", "Instalações elétricas", "Climatização e exaustão"):
        assert t in titles, t
    assert "sapatas isoladas" in _ch(m, "fundacoes")["text"] and "10,24 m³" in _ch(m, "fundacoes")["text"]
    assert "24 ×" in _ch(m, "eletrica")["text"]                            # 24 luminárias
    sug = _ch(m, "cobertura")["suggestions"]
    assert sug and any("COBERTURA" in s["section_path"] for s in sug)


# ------------------------------------------------------------------ API
def test_api(project_with_model):
    with TestClient(app) as c:
        pid = project_with_model["id"]
        r = c.post(f"/api/projects/{pid}/memorials", json={})
        assert r.status_code == 201
        m = r.json()
        assert c.get(f"/api/projects/{pid}/memorials").json()[0]["n_chapters"] == len(m["chapters"])
        cid = m["chapters"][2]["id"]
        assert c.patch(f"/api/memorial-chapters/{cid}", json={"text": "novo"}).json()["text"] == "novo"
        assert c.patch(f"/api/memorial-chapters/{cid}", json={"x": 1}).status_code == 422
        assert c.post(f"/api/memorial-chapters/{cid}/approve").json()["status"] == "aprovado"
        r = c.get(f"/api/memorials/{m['id']}/export", params={"draft": True})
        assert r.status_code == 200 and r.content[:2] == b"PK"
        assert "MINUTA" in r.headers["content-disposition"]
        assert c.get(f"/api/memorials/{m['id']}/export", params={"draft": False}).status_code == 409
        assert c.post(f"/api/memorial-chapters/{cid}/insert-reference", params={"chunk_id": 999}).status_code == 404
        assert c.get("/api/memorials/999").status_code == 404
        assert c.delete(f"/api/memorials/{m['id']}").status_code == 204
