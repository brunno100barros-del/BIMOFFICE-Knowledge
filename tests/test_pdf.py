"""Importação de PDF: leitura, seções, páginas reais, pesquisa, deduplicação e erros."""
import sqlite3

import pytest

from backend import config
from backend.database.db import get_conn, init_db
from backend.document_processing.pdf_parser import PdfWithoutText, parse_pdf
from backend.semantic_search import hybrid, vector_store
from backend.services import library_service as svc
from tests.conftest import PDF_PAGES, make_docx, make_pdf


def _imp_pdf(tmp_path, name="m.pdf", pages=PDF_PAGES, **meta):
    f = make_pdf(tmp_path / name, pages)
    return svc.import_document(name, f.read_bytes(), meta), f


def test_parse_pdf_sections_pages_and_cleanup(tmp_path):
    parsed = parse_pdf(make_pdf(tmp_path / "m.pdf", PDF_PAGES))
    titles = [s.title for s in parsed.sections]
    assert titles == ["1 DISPOSIÇÕES GERAIS", "2 REVESTIMENTOS", "2.1 Paredes",
                      "3 COBERTURA", "4 PINTURA"]
    assert [s.level for s in parsed.sections] == [1, 1, 2, 1, 1]
    text = " ".join(b.text for b in parsed.blocks)
    assert "MEMORIAL DESCRITIVO - SENAI" not in text      # cabeçalho repetido removido
    assert "Página" not in text                           # numeração de página removida
    assert "assentadas com argamassa" in text             # hifenização desfeita
    assert "isolamento termoacústico" in text             # linhas juntadas em parágrafo
    pint = [b for b in parsed.blocks if "acrílica" in b.text][0]
    assert pint.page == 3


def test_import_pdf_and_search(tmp_path):
    doc, src = _imp_pdf(tmp_path, unit="Porto Velho", discipline="Arquitetura")
    assert doc["file_type"] == "pdf" and doc["source"] == "upload"
    assert doc["n_sections"] == 5
    assert svc.original_path(doc["id"]).read_bytes() == src.read_bytes()
    assert svc.original_path(doc["id"]).suffix == ".pdf"
    chunks = svc.list_chunks(doc["id"])
    cob = [c for c in chunks if "telha" in c["text"]][0]
    assert cob["est_page"] == 2 and "3 COBERTURA" in cob["section_path"]
    assert svc.search_text("telha metálica")[0]["document_id"] == doc["id"]
    vector_store.index_pending()
    res = hybrid.search("banheiros placas cerâmicas", unit="Porto Velho")
    assert res["results"][0]["file_type"] == "pdf"
    assert "Paredes" in res["results"][0]["section_path"]


def test_pdf_and_docx_coexist_in_same_search(tmp_path):
    _imp_pdf(tmp_path)
    f = make_docx(tmp_path / "a.docx")
    svc.import_document("a.docx", f.read_bytes(), {})
    vector_store.index_pending()
    types = {r["file_type"] for r in hybrid.search("paredes", limit=20)["results"]}
    assert types == {"pdf", "docx"}
    st = svc.stats()
    assert (st["documents_total"], st["documents_docx"], st["documents_pdf"]) == (2, 1, 1)


def test_duplicate_pdf_detected(tmp_path):
    doc, f = _imp_pdf(tmp_path)
    with pytest.raises(svc.DuplicateDocument):
        svc.import_document("outro_nome.pdf", f.read_bytes(), {})


def test_scanned_pdf_without_text_is_rejected_clearly(tmp_path):
    f = make_pdf(tmp_path / "scan.pdf", [[], []])
    with pytest.raises(PdfWithoutText):
        parse_pdf(f)
    with pytest.raises(svc.InvalidFile, match="texto extraível"):
        svc.import_document("scan.pdf", f.read_bytes(), {})
    assert svc.list_documents() == []
    assert list(config.DOCUMENTS_DIR.iterdir()) == []  # nenhum arquivo órfão


def test_fake_pdf_rejected():
    with pytest.raises(svc.InvalidFile, match="PDF válido"):
        svc.import_document("x.pdf", b"isto nao e pdf", {})


def test_source_ref_is_stored(tmp_path):
    f = make_pdf(tmp_path / "d.pdf", PDF_PAGES)
    ref = {"drive_file_id": "abc", "folder": "Memoriais 2024"}
    doc = svc.import_document("d.pdf", f.read_bytes(), {}, source="gdrive", source_ref=ref)
    assert doc["source"] == "gdrive" and doc["source_ref"] == ref


def test_migration_adds_columns_to_old_database(tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.executescript("""CREATE TABLE documents (id INTEGER PRIMARY KEY, title TEXT NOT NULL,
        unit TEXT NOT NULL DEFAULT '', project TEXT NOT NULL DEFAULT '',
        discipline TEXT NOT NULL DEFAULT '', doc_date TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '[]',
        original_filename TEXT NOT NULL, sha256 TEXT NOT NULL, stored_path TEXT NOT NULL,
        n_sections INTEGER NOT NULL DEFAULT 0, n_chunks INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')), indexed_at TEXT, deleted_at TEXT);
        INSERT INTO documents(title, original_filename, sha256, stored_path)
        VALUES ('antigo', 'a.docx', 'x', 'x.docx');""")
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", old)
    init_db()
    with get_conn() as c:
        r = c.execute("SELECT title, file_type, source, source_ref FROM documents").fetchone()
    assert tuple(r) == ("antigo", "docx", "upload", "{}")
