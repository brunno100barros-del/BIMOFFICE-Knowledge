import sys
from pathlib import Path

import pytest
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config  # noqa: E402
from backend.database.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Cada teste usa uma pasta de dados temporária (nunca toca em dados reais)."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DOCUMENTS_DIR", tmp_path / "documents")
    monkeypatch.setattr(config, "DATABASE_DIR", tmp_path / "database")
    monkeypatch.setattr(config, "EMBEDDINGS_DIR", tmp_path / "embeddings")
    monkeypatch.setattr(config, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "database" / "t.db")
    config.ensure_dirs()
    init_db()


def make_docx(path: Path, styled: bool = True) -> Path:
    d = Document()
    if styled:
        d.add_heading("MEMORIAL DESCRITIVO – REFORMA UNIDADE SENAI", level=1)
        d.add_heading("Revestimentos", level=2)
        d.add_paragraph("Será executado revestimento cerâmico nas paredes dos sanitários.")
        d.add_paragraph("As placas terão dimensão mínima de 30x60 cm, assentadas com argamassa AC-II.")
        d.add_heading("Pintura", level=2)
        d.add_paragraph("As paredes internas receberão tinta acrílica fosca em duas demãos.")
        t = d.add_table(rows=2, cols=2)
        t.cell(0, 0).text, t.cell(0, 1).text = "Item", "Especificação"
        t.cell(1, 0).text, t.cell(1, 1).text = "Tinta", "Acrílica premium"
    else:  # títulos "digitados à mão", sem estilos
        d.add_paragraph("1 DISPOSIÇÕES GERAIS")
        d.add_paragraph("Este memorial descreve os serviços de reforma da unidade.")
        d.add_paragraph("1.1 Normas Técnicas")
        d.add_paragraph("Todos os serviços seguirão as normas da ABNT vigentes.")
        d.add_paragraph("2 COBERTURA")
        d.add_paragraph("A cobertura será em telha metálica trapezoidal com isolamento termoacústico.")
    d.save(path)
    return path


class FakeEmbeddingProvider:
    """SOMENTE PARA TESTES da mecânica (armazenamento, fusão RRF, filtros).
    Vetor = contagem de palavras com hash; NÃO mede significado e nunca é usado no sistema.
    A qualidade semântica real é testada em test_semantic_real.py com o modelo verdadeiro."""

    name = "fake-test-provider"
    dim = 256

    def _vec(self, text):
        import re

        import numpy as np
        v = np.zeros(self.dim, dtype=np.float32)
        for w in re.findall(r"\w+", text.lower()):
            v[hash(w) % self.dim] += 1
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_passages(self, texts):
        import numpy as np
        return np.vstack([self._vec(t) for t in texts])

    def embed_query(self, text):
        return self._vec(text)


@pytest.fixture(autouse=True)
def fake_embeddings():
    from backend.semantic_search import providers
    providers.set_provider(FakeEmbeddingProvider())
    yield
    providers.set_provider(None)


def make_pdf(path: Path, pages: list[list[str]]) -> Path:
    """Gera um PDF de TESTE com texto real (fonte Helvetica, acentos em WinAnsi).
    Cada página é uma lista de linhas. Página vazia = página sem texto."""
    def esc(s: str) -> bytes:
        b = s.encode("cp1252")
        return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")

    objs: list[bytes] = []
    n_pages = len(pages)
    page_ids = [3 + 2 * i for i in range(n_pages)]
    font_id = 3 + 2 * n_pages
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % p for p in page_ids)
                + b"] /Count %d >>" % n_pages)
    for i, lines in enumerate(pages):
        content = b""
        if lines:
            content = b"BT /F1 11 Tf 14 TL 50 800 Td " + b" ".join(
                b"(" + esc(l) + b") Tj T*" for l in lines) + b" ET"
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                    b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                    % (font_id, page_ids[i] + 1))
        objs.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                b"/Encoding /WinAnsiEncoding >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out))
    return path


PDF_PAGES = [
    ["MEMORIAL DESCRITIVO - SENAI", "1 DISPOSIÇÕES GERAIS",
     "Este memorial descreve os serviços de reforma do bloco de salas de aula,",
     "incluindo demolições, revestimentos e instalações.",
     "2 REVESTIMENTOS", "2.1 Paredes",
     "As paredes dos banheiros receberão acabamento em placas cerâmicas de 30x60 cm, assen-",
     "tadas com argamassa colante AC-II.", "Página 1 de 3"],
    ["MEMORIAL DESCRITIVO - SENAI", "3 COBERTURA",
     "A cobertura será executada em telha metálica trapezoidal com isolamento",
     "termoacústico em lã de rocha.", "Página 2 de 3"],
    ["MEMORIAL DESCRITIVO - SENAI", "4 PINTURA",
     "As paredes internas receberão tinta acrílica fosca em duas demãos.", "Página 3 de 3"],
]
