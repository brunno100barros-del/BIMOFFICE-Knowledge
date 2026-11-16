"""Leitor IFC: IFC2X3, IFC4 e IFC4X3 — elementos, propriedades, materiais, quantidades,
classificação por disciplina, erros e modelo grande."""
from pathlib import Path

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from backend.ifc.inventory import build_summary  # noqa: E402
from backend.ifc.reader import Cancelled, IfcReadError, read_ifc  # noqa: E402
from tests.ifc_factory import build_model  # noqa: E402

SAMPLES = Path(__file__).parent / "data" / "buildingsmart"


@pytest.fixture(scope="module", params=["IFC2X3", "IFC4"])
def model(request, tmp_path_factory):
    p = build_model(tmp_path_factory.mktemp("ifc") / f"t_{request.param}.ifc", request.param)
    return request.param, read_ifc(p)


def _el(r, name):
    return next(e for e in r["elements"] if e["name"] == name)


def _q(el, name):
    return next((q for q in el["quantities"] if q["name"] == name), None)


def test_schema_header_and_storeys(model):
    schema, r = model
    assert r["header"]["schema"] == schema
    assert r["header"]["project_name"] == "Projeto Teste BIMOFFICE"
    assert [s["name"] for s in r["storeys"]] == ["Térreo", "Pavimento 1"]
    assert r["storeys"][1]["elevation_m"] == 3.0
    assert len(r["elements"]) == 18
    assert _el(r, "Laje L1")["storey"] == "Pavimento 1"
    assert _el(r, "Sanitário masculino")["storey"] == "Térreo"


def test_explicit_quantities_properties_and_materials(model):
    _, r = model
    w = _el(r, "Parede externa 1")
    assert _q(w, "Length") == {"name": "Length", "value": 5.0, "unit": "m", "source": "Qto_WallBaseQuantities",
                               "method": "explicito", "note": None}
    assert _q(w, "NetVolume")["value"] == pytest.approx(2.1)
    assert _q(w, "Espessura (camadas de material)")["value"] == pytest.approx(0.14)
    assert [m["name"] for m in w["materials"]] == ["Argamassa de reboco", "Bloco cerâmico", "Argamassa de reboco"]
    assert w["material_set"]["kind"] == "camadas"
    assert w["psets"]["Pset_WallCommon"]["FireRating"] == "EI 60"
    assert w["classification"][0]["code"] == "Ss_25_10_30"
    assert w["missing"] == []
    door = _el(r, "Porta P1")
    assert _q(door, "OverallHeight")["value"] == pytest.approx(2.1) and _q(door, "OverallHeight")["method"] == "atributo"
    assert _q(_el(r, "Sanitário masculino"), "NetFloorArea")["value"] == 12.5


def test_geometric_quantities_are_real_solid_not_bounding_box(model):
    _, r = model
    w = _el(r, "Parede interna sem quantitativos")  # 4 x 3 x 0,14 m, sem Qto
    v = _q(w, "Volume (malha 3D)")
    assert v["method"] == "geometrico" and v["value"] == pytest.approx(1.68, abs=1e-6)
    assert _q(w, "Área lateral (malha 3D)")["value"] == pytest.approx(12.0, abs=1e-6)
    assert "caixa envolvente" in v["note"]
    # elemento com volume explícito NÃO recebe volume geométrico (não duplica)
    assert _q(_el(r, "Parede externa 1"), "Volume (malha 3D)") is None
    # o que não existe não é inventado
    assert "material" in w["missing"] and "espessura" in w["missing"]


def test_discipline_classification(model):
    schema, r = model
    d = {e["name"]: (e["discipline"], e["confidence"]) for e in r["elements"]}
    assert d["Parede externa 1"] == ("Arquitetura", "alta")       # LoadBearing = falso
    assert d["Parede de contenção"] == ("Estrutura", "alta")      # LoadBearing = verdadeiro
    assert d["Laje L1"] == ("Estrutura", "alta")
    assert d["P1 - pilar de concreto"] == ("Estrutura", "alta")
    assert d["P2 - pilar metálico"] == ("Estrutura metálica", "alta")
    assert d["V1 - viga metálica"] == ("Estrutura metálica", "alta")
    assert d["Tubo AF 25 mm"] == ("Hidrossanitário", "alta")       # IFC2X3: pelo TIPO; IFC4: pela classe
    assert d["Lavatório"] == ("Hidrossanitário", "alta")
    assert d["Luminária LED"] == ("Elétrica", "alta")
    assert d["Duto de insuflamento"] == ("Climatização", "alta")
    assert d["Porta P1"][0] == "Arquitetura"
    if schema == "IFC2X3":
        assert "tipo associado IfcPipeSegmentType" in _el(r, "Tubo AF 25 mm")["reasons"]


def test_name_alone_never_classifies(model):
    _, r = model
    ralo = _el(r, "Ralo sifonado")
    assert ralo["discipline"] == "Pendente" and ralo["confidence"] == "baixa"
    assert ralo["suggestion"]["discipline"] == "Hidrossanitário"
    assert "nome" in ralo["suggestion"]["reason"]
    assert _el(r, "Elemento 123")["suggestion"] is None


def test_inventory_summary(model):
    _, r = model
    s = build_summary(r)
    assert s["elements_total"] == 18
    assert s["disciplines"]["Hidrossanitário"]["total"] == 2
    assert s["pending_classification"] == 2
    mats = {m["name"]: m["elements"] for m in s["materials"]}
    assert mats["Concreto C30"] == 4 and mats["Aço ASTM A572"] == 2
    walls = [t for t in s["quantity_totals"] if t["quantity"] == "NetSideArea"]
    assert walls[0]["total"] == pytest.approx(30.0) and walls[0]["method"] == "explicito"
    geo = [t for t in s["quantity_totals"] if t["method"] == "geometrico" and t["quantity"].startswith("Volume")]
    assert geo[0]["total"] == pytest.approx(1.68)  # métodos nunca misturados no mesmo total
    assert s["missing_info"]["volume"] >= 4  # pilares/viga/sapata sem volume e sem geometria


@pytest.mark.parametrize("fname,schema", [
    ("ifc2x3_building-architecture.ifc", "IFC2X3"),
    ("ifc2x3_building-structural.ifc", "IFC2X3"),
    ("ifc4_building-architecture.ifc", "IFC4"),
    ("ifc4_building-hvac.ifc", "IFC4"),
    ("ifc4x3_building-architecture.ifc", "IFC4X3"),
])
def test_official_buildingsmart_samples(fname, schema):
    r = read_ifc(SAMPLES / fname)
    assert r["header"]["schema"].startswith(schema)
    assert r["elements"] and not any(e.get("read_error") for e in r["elements"])
    assert r["units"]["length_scale_to_m"] == pytest.approx(0.001)  # modelos em milímetros
    for e in r["elements"]:
        for q in e["quantities"]:
            if q["unit"] == "m":
                assert 0 < q["value"] < 1000, (e["name"], q)  # convertidos para metros


def test_official_mm_units_converted():
    r = read_ifc(SAMPLES / "ifc2x3_building-architecture.ifc")
    walls = [e for e in r["elements"] if e["ifc_class"].startswith("IfcWall")]
    widths = {q["value"] for w in walls for q in w["quantities"] if q["name"] == "Width"}
    assert 0.2 in {round(x, 3) for x in widths}  # 200 mm -> 0,2 m


def test_hvac_sample_classification():
    r = read_ifc(SAMPLES / "ifc4_building-hvac.ifc")
    discs = {e["ifc_class"]: e["discipline"] for e in r["elements"]}
    assert discs["IfcAirTerminal"] == "Climatização" and discs["IfcDuctSegment"] == "Climatização"


def test_invalid_files(tmp_path):
    p = tmp_path / "x.ifc"
    p.write_text("isto não é IFC")
    with pytest.raises(IfcReadError, match="STEP"):
        read_ifc(p)
    good = (SAMPLES / "ifc4_building-hvac.ifc").read_text(errors="ignore")
    p.write_text(good[: len(good) // 3])  # truncado
    with pytest.raises(IfcReadError):
        read_ifc(p)
    p.write_text(good.replace("FILE_SCHEMA(('IFC4'))", "FILE_SCHEMA(('IFC2X2_FINAL'))"))
    with pytest.raises(IfcReadError):
        read_ifc(p)


def test_cancel(tmp_path):
    p = build_model(tmp_path / "c.ifc", "IFC4")
    with pytest.raises(Cancelled):
        read_ifc(p, should_cancel=lambda: True)


def test_larger_model_is_read(tmp_path):
    p = build_model(tmp_path / "grande.ifc", "IFC4", n_extra_walls=1500)
    r = read_ifc(p, geometry=False)
    assert len(r["elements"]) == 18 + 1500
    assert r["parse_seconds"] < 60
    s = build_summary(r)
    assert s["classes"]["IfcWall"] == 1504


def test_non_additive_dimensions_are_not_summed(model):
    _, r = model
    s = build_summary(r)
    names = {t["quantity"] for t in s["quantity_totals"]}
    assert "Length" in names                       # comprimento total de paredes faz sentido
    for bad in ("Height", "Width", "Espessura (camadas de material)", "OverallHeight", "OverallWidth"):
        assert bad not in names, bad               # somar espessuras/alturas não faz sentido
