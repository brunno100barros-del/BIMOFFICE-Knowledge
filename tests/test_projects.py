"""Projetos: arquivos, duplicados, versões, tarefas em segundo plano, inventário IFC persistido e API."""
import io
import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("ifcopenshell")

from backend import config, jobs  # noqa: E402
from backend.database.db import get_conn  # noqa: E402
from backend.main import app  # noqa: E402
from backend.projects import service as svc  # noqa: E402
from tests.conftest import PDF_PAGES, make_pdf  # noqa: E402
from tests.ifc_factory import build_model  # noqa: E402

SAMPLES = Path(__file__).parent / "data" / "buildingsmart"


@pytest.fixture
def ifc4(tmp_path):
    return build_model(tmp_path / "Arquitetura.ifc", "IFC4")


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _store(pid, path, name=None):
    with open(path, "rb") as fh:
        return svc.store_file(pid, name or Path(path).name, fh)


def test_project_crud_and_history():
    p = svc.create_project("Reforma Bloco A", "Salas de aula", "Porto Velho/RO", ["Arquitetura"])
    assert p["disciplines"] == ["Arquitetura"] and p["file_counts"] == {}
    svc.update_project(p["id"], {"name": "Reforma Bloco A2"})
    hist = svc.list_history(p["id"])
    assert hist[0]["event"] == "dados do projeto alterados"
    assert hist[0]["detail"]["name"] == {"antes": "Reforma Bloco A", "depois": "Reforma Bloco A2"}
    with pytest.raises(svc.ProjectError):
        svc.create_project("   ")
    svc.delete_project(p["id"])
    with pytest.raises(svc.NotFound):
        svc.get_project(p["id"])


def test_ifc_upload_is_processed_in_background_and_persisted(ifc4):
    p = svc.create_project("P")
    f, job = _store(p["id"], ifc4)
    assert f["kind"] == "ifc" and f["status"] == "na fila" and f["version"] == 1
    assert job["status"] == "na fila"                       # não processou dentro da requisição
    assert jobs.run_pending() == 1
    j = jobs.get(job["id"])
    assert j["status"] == "concluído" and j["progress"] == 1
    f = svc.get_file(f["id"])
    assert f["status"] == "processado" and f["ifc_model"]["n_elements"] == 18
    # persistido no banco (não só em memória)
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ifc_elements").fetchone()[0] == 18
    m = svc.list_models(p["id"])[0]
    assert m["schema_name"] == "IFC4" and m["summary"]["elements_total"] == 18
    # original guardado intacto e somente leitura
    stored = svc.file_path(f["id"])
    assert stored.read_bytes() == ifc4.read_bytes()
    assert not (stored.stat().st_mode & stat.S_IWUSR)
    assert svc.list_history(p["id"])[0]["event"] == "IFC processado"


def test_element_filters_and_detail(ifc4):
    p = svc.create_project("P")
    f, _ = _store(p["id"], ifc4)
    jobs.run_pending()
    mid = svc.get_file(f["id"])["ifc_model"]["id"]
    assert svc.list_elements(mid, discipline="Hidrossanitário")["total"] == 2
    assert svc.list_elements(mid, ifc_class="IfcWall")["total"] == 4
    assert svc.list_elements(mid, storey="Pavimento 1")["total"] == 1
    assert svc.list_elements(mid, q="pilar")["total"] == 2
    assert svc.list_elements(mid, missing="material")["total"] >= 1
    page = svc.list_elements(mid, limit=5, offset=5)
    assert page["total"] == 18 and len(page["items"]) == 5
    eid = svc.list_elements(mid, q="Parede externa 1")["items"][0]["id"]
    el = svc.get_element(eid)
    assert el["psets"]["Pset_WallCommon"]["FireRating"] == "EI 60"
    assert any(q["method"] == "explicito" and q["name"] == "NetVolume" for q in el["quantities"])
    exp = svc.export_inventory(mid)
    assert exp["format"] == "bimoffice.ifc-inventory/1" and len(exp["elements"]) == 18


def test_duplicate_and_versions(tmp_path, ifc4):
    p = svc.create_project("P")
    f1, _ = _store(p["id"], ifc4)
    with pytest.raises(svc.Duplicate):
        _store(p["id"], ifc4, "outro_nome.ifc")             # mesmo conteúdo, outro nome
    (tmp_path / "v2").mkdir()
    v2 = build_model(tmp_path / "v2" / "Arquitetura.ifc", "IFC2X3")
    f2, _ = _store(p["id"], v2, "Arquitetura.ifc")          # mesmo nome, conteúdo novo
    assert f2["version"] == 2 and f2["previous_file_id"] == f1["id"]
    jobs.run_pending()
    assert {m["schema_name"] for m in svc.list_models(p["id"])} == {"IFC4", "IFC2X3"}
    # o mesmo arquivo em OUTRO projeto é aceito (e o disco não duplica)
    q = svc.create_project("Q")
    _store(q["id"], ifc4)
    assert len(list(config.PROJECT_FILES_DIR.glob("*.ifc"))) == 2


def test_invalid_and_unsupported_files(tmp_path):
    p = svc.create_project("P")
    bad = tmp_path / "x.ifc"
    bad.write_text("nada")
    with pytest.raises(svc.InvalidFile, match="IFC"):
        _store(p["id"], bad)
    dwg = tmp_path / "planta.dwg"
    dwg.write_bytes(b"AC1032")
    with pytest.raises(svc.InvalidFile, match="DWG"):
        _store(p["id"], dwg)
    with pytest.raises(svc.InvalidFile, match="Tipo não aceito"):
        svc.store_file(p["id"], "a.xlsx", io.BytesIO(b"x"))
    with pytest.raises(svc.InvalidFile, match="vazio"):
        svc.store_file(p["id"], "a.ifc", io.BytesIO(b""))
    assert list(config.PROJECT_FILES_DIR.glob("*.part")) == []   # nenhum resto de envio
    assert svc.list_files(p["id"]) == []


def test_truncated_ifc_fails_in_job_with_clear_message(tmp_path):
    p = svc.create_project("P")
    t = tmp_path / "cortado.ifc"
    src = (SAMPLES / "ifc4_building-hvac.ifc").read_bytes()
    t.write_bytes(src[: len(src) // 2])
    f, job = _store(p["id"], t)
    jobs.run_pending()
    assert jobs.get(job["id"])["status"] == "erro"
    f = svc.get_file(f["id"])
    assert f["status"] == "erro" and "incompleto" in f["error"]


def test_other_project_files_are_stored_not_processed(tmp_path):
    p = svc.create_project("P")
    pdf = make_pdf(tmp_path / "Memorial.pdf", PDF_PAGES)
    f, job = _store(p["id"], pdf)
    assert f["kind"] == "pdf" and f["status"] == "armazenado" and job is None


def test_cancel_and_recovery(ifc4):
    p = svc.create_project("P")
    f, job = _store(p["id"], ifc4)
    jobs.cancel(job["id"])
    assert jobs.get(job["id"])["status"] == "cancelado"
    assert jobs.run_pending() == 0
    # retomada: tarefa "executando" quando o servidor caiu volta para a fila
    j2 = svc.reprocess(p["id"], f["id"])
    with get_conn() as conn:
        conn.execute("UPDATE jobs SET status='executando', attempts=1 WHERE id=?", (j2["id"],))
    assert jobs.recover() == 1 and jobs.get(j2["id"])["status"] == "na fila"
    jobs.run_pending()
    assert jobs.get(j2["id"])["status"] == "concluído"
    # tentativas demais -> erro, não fica em laço infinito
    j3 = svc.reprocess(p["id"], f["id"])
    with get_conn() as conn:
        conn.execute("UPDATE jobs SET status='executando', attempts=? WHERE id=?", (config.JOB_MAX_ATTEMPTS, j3["id"]))
    jobs.recover()
    assert jobs.get(j3["id"])["status"] == "erro"


def test_reprocess_replaces_inventory_without_duplicating(ifc4):
    p = svc.create_project("P")
    f, _ = _store(p["id"], ifc4)
    jobs.run_pending()
    svc.reprocess(p["id"], f["id"])
    jobs.run_pending()
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ifc_models").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM ifc_elements").fetchone()[0] == 18


def test_projects_do_not_touch_library(ifc4):
    from backend.services import library_service as lib
    before = lib.stats()
    p = svc.create_project("P")
    _store(p["id"], ifc4)
    jobs.run_pending()
    after = lib.stats()
    assert (before["documents_total"], before["chunks_total"]) == (after["documents_total"], after["chunks_total"])


# ------------------------------------------------------------------ API
def test_api_flow(client, ifc4):
    r = client.post("/api/projects", json={"name": "Escola SENAI", "location": "Ji-Paraná"})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert client.post("/api/projects", json={"name": "x", "foo": 1}).status_code == 422
    r = client.post(f"/api/projects/{pid}/files", files={"file": ("Arquitetura.ifc", ifc4.read_bytes())},
                    data={"discipline": "Arquitetura"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["file"]["discipline"] == "Arquitetura" and body["job"]["status"] == "na fila"
    jobs.run_pending()
    assert client.get(f"/api/jobs/{body['job']['id']}").json()["status"] == "concluído"
    r = client.post(f"/api/projects/{pid}/files", files={"file": ("copia.ifc", ifc4.read_bytes())})
    assert r.status_code == 409 and r.json()["detail"]["existing_file_id"] == body["file"]["id"]
    assert client.post(f"/api/projects/{pid}/files", files={"file": ("a.dwg", b"AC10")}).status_code == 400
    models = client.get(f"/api/projects/{pid}/ifc-models").json()
    mid = models[0]["id"]
    assert models[0]["summary"]["disciplines"]["Elétrica"]["total"] == 1
    els = client.get(f"/api/ifc-models/{mid}/elements", params={"discipline": "Estrutura metálica"}).json()
    assert els["total"] == 2
    el = client.get(f"/api/ifc-elements/{els['items'][0]['id']}").json()
    assert el["discipline"] == "Estrutura metálica" and el["reasons"]
    r = client.get(f"/api/projects/{pid}/files/{body['file']['id']}/original")
    assert r.status_code == 200 and r.content == ifc4.read_bytes()
    assert client.get(f"/api/ifc-models/{mid}/export").json()["format"] == "bimoffice.ifc-inventory/1"
    assert client.get("/api/config").json()["ifc"]["available"] is True
    assert client.delete(f"/api/projects/{pid}/files/{body['file']['id']}").status_code == 204
    assert client.get(f"/api/projects/{pid}/ifc-models").json() == []
    assert client.get("/api/projects/999").status_code == 404
    assert client.get("/api/ifc-models/999").status_code == 404


def test_api_official_sample_ifc2x3(client):
    pid = client.post("/api/projects", json={"name": "Amostra buildingSMART"}).json()["id"]
    data = (SAMPLES / "ifc2x3_building-structural.ifc").read_bytes()
    r = client.post(f"/api/projects/{pid}/files", files={"file": ("estrutura.ifc", data)})
    assert r.status_code == 201
    jobs.run_pending()
    m = client.get(f"/api/projects/{pid}/ifc-models").json()[0]
    assert m["schema_name"] == "IFC2X3" and m["n_elements"] > 10
    assert m["summary"]["disciplines"]["Estrutura"]["total"] >= 6  # vigas + sapata
