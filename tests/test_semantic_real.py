"""Qualidade semântica com o MODELO REAL (intfloat/multilingual-e5-base).

É pulado automaticamente se o modelo não estiver instalado/baixado
(pip install -r requirements-ml.txt e uma primeira execução com internet).
"""
import numpy as np
import pytest

from backend import config
from backend.semantic_search.providers import (
    EmbeddingUnavailable, SentenceTransformerProvider, set_provider,
)


@pytest.fixture(scope="module")
def real():
    p = SentenceTransformerProvider(config.EMBEDDING_MODEL)
    try:
        p.embed_query("teste")
    except EmbeddingUnavailable as e:
        pytest.skip(f"modelo real indisponível: {e}")
    return p


QUERY = "Será executado revestimento cerâmico nas paredes dos sanitários."
SIMILAR = "As paredes dos banheiros receberão acabamento em placas cerâmicas."
UNRELATED = [
    "A cobertura será em telha metálica trapezoidal com isolamento termoacústico.",
    "As instalações elétricas seguirão a NBR 5410, com quadros de distribuição embutidos.",
    "O concreto estrutural das vigas terá fck mínimo de 30 MPa.",
]


def test_similar_meaning_beats_unrelated(real):
    q = real.embed_query(QUERY)
    p = real.embed_passages([SIMILAR, *UNRELATED])
    sims = p @ q
    assert np.argmax(sims) == 0, sims
    assert sims[0] - max(sims[1:]) > 0.03, sims


def test_hybrid_end_to_end_with_real_model(real, tmp_path):
    from docx import Document

    from backend.semantic_search import hybrid, vector_store
    from backend.services import library_service as svc
    d = Document()
    d.add_heading("Acabamentos", level=1)
    d.add_paragraph(SIMILAR)
    for t in UNRELATED:
        d.add_heading("Outro serviço", level=1)
        d.add_paragraph(t)
    d.save(tmp_path / "m.docx")
    svc.import_document("m.docx", (tmp_path / "m.docx").read_bytes(), {})
    set_provider(real)
    vector_store.index_pending()
    res = hybrid.search(QUERY, mode="semantic")
    assert res["semantic_used"]
    assert SIMILAR in res["results"][0]["text"]
