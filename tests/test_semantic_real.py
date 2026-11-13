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
    # Avaliado pela POSIÇÃO: no E5 os cossenos ficam comprimidos (~0,80–0,90) e a margem
    # entre o correto e o errado é pequena (~0,01–0,04). Por isso o cosseno não é exibido
    # como porcentagem; a interface mostra a relevância relativa.
    assert np.argmax(sims) == 0, sims


# Paráfrases técnicas sem palavras em comum (consulta, trecho equivalente).
PARES = [
    ("Será executado revestimento cerâmico nas paredes dos sanitários.",
     "As paredes dos banheiros receberão acabamento em placas cerâmicas."),
    ("A cobertura será em telha metálica trapezoidal.",
     "O telhado terá telhas de aço com perfil trapezoidal."),
    ("As lajes de cobertura receberão impermeabilização com manta asfáltica.",
     "Sobre a laje do telhado será aplicada manta betuminosa para estanqueidade."),
    ("As paredes internas receberão tinta acrílica fosca em duas demãos.",
     "Pintar as alvenarias internas com duas camadas de acrílico acabamento fosco."),
    ("Os quadros de distribuição de energia serão embutidos.",
     "Os painéis elétricos ficarão instalados dentro da parede."),
    ("As esquadrias serão em alumínio anodizado com vidro temperado 6 mm.",
     "Janelas e portas de alumínio com vidros de segurança de seis milímetros."),
    ("O piso das salas será em porcelanato polido 60x60 cm.",
     "Nas salas de aula o pavimento terá placas de grés polido de 60 por 60."),
    ("O concreto estrutural terá resistência característica mínima de 30 MPa.",
     "O fck mínimo exigido para pilares e vigas é de 30 MPa."),
    ("As tubulações de água fria serão em PVC soldável.",
     "A rede hidráulica de água potável usará tubos de policloreto de vinila com junta colada."),
    ("Será instalado forro de gesso acartonado nas circulações.",
     "Os corredores terão teto rebaixado em placas de drywall."),
]


def test_paraphrase_quality_benchmark(real):
    """Linha de base medida em 2026-11: 8/10 em 1º lugar, todos entre os 3 primeiros.
    Serve para detectar piora ao trocar modelo/configuração."""
    Q = np.vstack([real.embed_query(a) for a, _ in PARES])
    P = real.embed_passages([b for _, b in PARES])
    S = Q @ P.T
    ranks = [int((S[i] > S[i, i]).sum()) + 1 for i in range(len(PARES))]
    assert sum(r == 1 for r in ranks) >= 7, ranks
    assert max(ranks) <= 3, ranks


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
