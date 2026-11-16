"""Arquivos originais em armazenamento S3 (simulado pelo moto — nenhum acesso à internet)."""
import hashlib
import io

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from backend import config, jobs, storage
from backend.main import app
from backend.projects import service as psvc
from backend.services import library_service as lib
from tests.conftest import make_docx, make_pdf, PDF_PAGES

BUCKET = "bimoffice-s3-teste"


@pytest.fixture
def s3(monkeypatch):
    with mock_aws():
        storage._cache.clear()
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "teste")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "teste")
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        monkeypatch.setattr(config, "STORAGE", "s3")
        monkeypatch.setattr(config, "S3_BUCKET", BUCKET)
        monkeypatch.setattr(config, "S3_PREFIX", "bimoffice/")
        monkeypatch.setattr(config, "S3_REGION", "us-east-1")
        yield client
        storage._cache.clear()


def _obj(client, key):
    return client.get_object(Bucket=BUCKET, Key=f"bimoffice/{key}")["Body"].read()


def test_library_original_goes_to_bucket_byte_for_byte(s3, tmp_path):
    data = make_docx(tmp_path / "a.docx").read_bytes()
    doc = lib.import_document("a.docx", data, {})
    assert _obj(s3, f"documents/{doc['sha256']}.docx") == data
    assert not any(config.DOCUMENTS_DIR.glob("*"))                     # nada no disco local
    assert lib.search_text("sanitarios")                                # indexado a partir do S3
    lib.reindex_document(doc["id"])                                     # relê do S3
    assert _obj(s3, f"documents/{doc['sha256']}.docx") == data          # original intacto


def test_failed_import_leaves_no_object(s3, tmp_path):
    pdf = make_pdf(tmp_path / "scan.pdf", [[]])
    with pytest.raises(lib.InvalidFile):
        lib.import_document("scan.pdf", pdf.read_bytes(), {})
    assert s3.list_objects_v2(Bucket=BUCKET).get("KeyCount", 0) == 0


def test_project_ifc_processed_from_bucket(s3, tmp_path):
    from tests.ifc_factory import build_model
    ifc = build_model(tmp_path / "m.ifc", "IFC4")
    p = psvc.create_project("P")
    with open(ifc, "rb") as fh:
        f, job = psvc.store_file(p["id"], "m.ifc", fh)
    jobs.run_pending()
    assert psvc.get_file(f["id"])["status"] == "processado"
    sha = hashlib.sha256(ifc.read_bytes()).hexdigest()
    assert _obj(s3, f"projects/{sha}.ifc") == ifc.read_bytes()
    # o mesmo arquivo em outro projeto não duplica o objeto
    q = psvc.create_project("Q")
    psvc.store_file(q["id"], "m.ifc", io.BytesIO(ifc.read_bytes()))
    assert s3.list_objects_v2(Bucket=BUCKET, Prefix="bimoffice/projects/")["KeyCount"] == 1


def test_download_routes_stream_from_bucket(s3, tmp_path):
    with TestClient(app) as c:
        data = make_pdf(tmp_path / "m.pdf", PDF_PAGES).read_bytes()
        did = c.post("/api/library/documents", files={"file": ("m.pdf", data)}).json()["id"]
        r = c.get(f"/api/library/documents/{did}/original", params={"inline": True})
        assert r.status_code == 200 and r.content == data
        assert r.headers["content-disposition"].startswith("inline")
        pid = c.post("/api/projects", json={"name": "P"}).json()["id"]
        fid = c.post(f"/api/projects/{pid}/files", files={"file": ("m.pdf", data)}).json()["file"]["id"]
        r = c.get(f"/api/projects/{pid}/files/{fid}/original")
        assert r.status_code == 200 and r.content == data


def test_storage_check(s3):
    assert storage.get_storage().check()["bucket"] == BUCKET
