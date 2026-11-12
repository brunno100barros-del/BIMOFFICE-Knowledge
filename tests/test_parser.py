from backend.document_processing.chunker import chunk_document
from backend.document_processing.docx_parser import parse_docx
from tests.conftest import make_docx


def test_headings_by_style_and_hierarchy(tmp_path):
    p = parse_docx(make_docx(tmp_path / "a.docx"))
    titles = [(s.level, s.title) for s in p.sections]
    assert titles == [
        (1, "MEMORIAL DESCRITIVO – REFORMA UNIDADE SENAI"),
        (2, "Revestimentos"),
        (2, "Pintura"),
    ]
    assert p.sections[1].path.endswith("> Revestimentos")


def test_table_extracted_as_text(tmp_path):
    p = parse_docx(make_docx(tmp_path / "a.docx"))
    tables = [b for b in p.blocks if b.kind == "table"]
    assert len(tables) == 1 and "Tinta | Acrílica premium" in tables[0].text
    assert tables[0].section_path.endswith("Pintura")


def test_heuristic_headings_without_styles(tmp_path):
    p = parse_docx(make_docx(tmp_path / "b.docx", styled=False))
    got = [(s.level, s.title) for s in p.sections]
    assert (1, "1 DISPOSIÇÕES GERAIS") in got
    assert (2, "1.1 Normas Técnicas") in got
    assert (1, "2 COBERTURA") in got


def test_chunks_never_mix_sections(tmp_path):
    p = parse_docx(make_docx(tmp_path / "a.docx"))
    chunks = chunk_document(p)
    assert chunks
    for c in chunks:
        assert "tinta acrílica" not in c.text.lower() or c.section_path.endswith("Pintura")
        assert "cerâmico" not in c.text.lower() or c.section_path.endswith("Revestimentos")


def test_long_section_is_split(tmp_path):
    from docx import Document
    d = Document()
    d.add_heading("Estrutura", level=1)
    for i in range(40):
        d.add_paragraph(f"Parágrafo {i}: " + "concreto armado fck 30 MPa. " * 12)
    d.save(tmp_path / "long.docx")
    chunks = chunk_document(parse_docx(tmp_path / "long.docx"))
    assert len(chunks) > 5
    assert all(len(c.text) <= 1800 * 1.25 for c in chunks)
    assert all(c.section_path == "Estrutura" for c in chunks)
