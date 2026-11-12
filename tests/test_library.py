import hashlib
import os
import stat

import pytest

from backend import config
from backend.services import library_service as svc
from tests.conftest import make_docx


def _import(tmp_path, name="a.docx", styled=True, **meta):
    f = make_docx(tmp_path / name, styled)
    return svc.import_document(name, f.read_bytes(), meta), f


def test_import_creates_document_sections_chunks(tmp_path):
    doc, _ = _import(tmp_path, title="Reforma X", unit="SENAI Porto Velho",
                     discipline="Arquitetura", tags="piso, pintura ,piso")
    assert doc["title"] == "Reforma X"
    assert doc["tags"] == ["pintura", "piso"]
    assert doc["n_sections"] == 3 and doc["n_chunks"] >= 2
    assert len(svc.list_chunks(doc["id"])) == doc["n_chunks"]


def test_original_is_preserved_byte_for_byte_and_readonly(tmp_path):
    doc, src = _import(tmp_path)
    stored = svc.original_path(doc["id"])
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == doc["sha256"]
    assert stored.read_bytes() == src.read_bytes()
    assert not os.access(stored, os.W_OK) or os.geteuid() == 0  # root ignora permissões
    assert not (stored.stat().st_mode & stat.S_IWUSR)


def test_reindex_and_delete_do_not_touch_original(tmp_path):
    doc, _ = _import(tmp_path)
    stored = svc.original_path(doc["id"])
    before = (stored.read_bytes(), stored.stat().st_mtime_ns)
    svc.reindex_document(doc["id"])
    svc.delete_document(doc["id"])
    assert (stored.read_bytes(), stored.stat().st_mtime_ns) == before


def test_duplicate_is_detected(tmp_path):
    doc, f = _import(tmp_path)
    with pytest.raises(svc.DuplicateDocument) as e:
        svc.import_document("copia.docx", f.read_bytes(), {})
    assert e.value.existing_id == doc["id"]


@pytest.mark.parametrize("name,data", [
    ("x.pdf", b"%PDF"), ("x.docx", b""), ("x.docx", b"nao e zip"),
])
def test_invalid_files_rejected(name, data):
    with pytest.raises(svc.InvalidFile):
        svc.import_document(name, data, {})


def test_zip_without_word_xml_rejected(tmp_path):
    import zipfile
    z = tmp_path / "f.docx"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.txt", "oi")
    with pytest.raises(svc.InvalidFile):
        svc.import_document("f.docx", z.read_bytes(), {})


def test_failed_import_leaves_no_orphan(tmp_path):
    from docx import Document
    empty = tmp_path / "vazio.docx"
    Document().save(empty)  # sem texto
    with pytest.raises(svc.InvalidFile):
        svc.import_document("vazio.docx", empty.read_bytes(), {})
    assert list(config.DOCUMENTS_DIR.iterdir()) == []
    assert svc.list_documents() == []


def test_text_search_ignores_accents_and_respects_filters(tmp_path):
    a, _ = _import(tmp_path, "a.docx", unit="Porto Velho", discipline="Arquitetura")
    _import(tmp_path, "b.docx", styled=False, unit="Ji-Paraná", discipline="Cobertura")
    hits = svc.search_text("sanitarios")  # sem acento acha "sanitários"
    assert hits and hits[0]["document_id"] == a["id"]
    assert "[" in hits[0]["snippet"]
    assert svc.search_text("telha metalica")[0]["unit"] == "Ji-Paraná"
    assert svc.search_text("sanitarios", unit="Ji-Paraná") == []


def test_search_query_with_special_characters_is_safe(tmp_path):
    _import(tmp_path)
    assert svc.search_text('tinta" OR (* NEAR') is not None  # não levanta erro FTS
    assert svc.search_text("   ") == []


def test_delete_is_soft_and_restore_works(tmp_path):
    doc, f = _import(tmp_path)
    svc.delete_document(doc["id"])
    assert svc.list_documents() == []
    assert svc.search_text("sanitarios") == []
    assert list(config.BACKUPS_DIR.glob("*.db"))  # backup antes de excluir
    assert (config.DOCUMENTS_DIR / f"{doc['sha256']}.docx").exists()
    # restaurar reindexa e devolve o documento às buscas
    svc.restore_document(doc["id"])
    assert svc.search_text("sanitarios")


def test_filters_and_metadata_update(tmp_path):
    a, _ = _import(tmp_path, "a.docx", unit="Porto Velho", tags="piso")
    _import(tmp_path, "b.docx", styled=False, unit="Vilhena")
    assert [d["id"] for d in svc.list_documents(unit="porto velho")] == [a["id"]]
    assert len(svc.list_documents(tag="PISO")) == 1
    upd = svc.update_metadata(a["id"], {"discipline": "Elétrica", "tags": ["x", "y"]})
    assert upd["discipline"] == "Elétrica" and upd["tags"] == ["x", "y"]


def test_not_found(tmp_path):
    with pytest.raises(svc.NotFound):
        svc.get_document(999)
