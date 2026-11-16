"""Leitor IFC (IfcOpenShell) — extrai elementos, propriedades, materiais e quantidades.

Princípios:
- Somente leitura: o arquivo IFC original nunca é alterado.
- Nada é inventado. Cada quantidade registra a ORIGEM e o MÉTODO:
    "explicito"  -> gravado no IFC (IfcElementQuantity / Qto_* ou camadas de material)
    "atributo"   -> atributo do próprio elemento (ex.: IfcDoor.OverallHeight)
    "geometrico" -> calculado pela malha 3D real do elemento (IfcOpenShell geom), NÃO pela
                    caixa envolvente; aproximação geométrica — não é quantitativo executivo
- Unidades convertidas para SI (m, m², m³, kg) a partir das unidades do projeto IFC.
"""
from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from pathlib import Path

from backend.ifc.classify import AUXILIARY, classify

log = logging.getLogger("bimoffice.ifc")

SUPPORTED_SCHEMAS = ("IFC2X3", "IFC4", "IFC4X1", "IFC4X2", "IFC4X3")
QTY_KIND = {  # entidade -> (atributo do valor, tipo de unidade, símbolo SI)
    "IfcQuantityLength": ("LengthValue", "LENGTHUNIT", "m"),
    "IfcQuantityArea": ("AreaValue", "AREAUNIT", "m²"),
    "IfcQuantityVolume": ("VolumeValue", "VOLUMEUNIT", "m³"),
    "IfcQuantityWeight": ("WeightValue", "MASSUNIT", "kg"),
    "IfcQuantityCount": ("CountValue", None, "un"),
    "IfcQuantityTime": ("TimeValue", None, "s"),
}
# sinônimos para conferir o que existe por elemento
INFO_KEYS = {
    "espessura": {"Width", "Thickness", "Espessura (camadas de material)"},
    "comprimento": {"Length"},
    "altura": {"Height", "OverallHeight"},
    "largura": {"OverallWidth", "Width"},
    "área": {"NetSideArea", "GrossSideArea", "NetArea", "GrossArea", "NetFloorArea", "GrossFloorArea",
             "OuterSurfaceArea", "Área lateral (malha 3D)", "Área de projeção (malha 3D)",
             "Área de piso (malha 3D)"},
    "volume": {"NetVolume", "GrossVolume", "Volume (malha 3D)"},
}
EXPECTED = {  # o que um memorial normalmente precisa por categoria
    "Wall": ["material", "espessura", "comprimento", "altura", "área"],
    "Slab": ["material", "espessura", "área"],
    "Roof": ["material", "área"],
    "Covering": ["material", "área"],
    "Door": ["largura", "altura"],
    "Window": ["largura", "altura"],
    "Column": ["material", "volume"],
    "Beam": ["material", "volume"],
    "Footing": ["material", "volume"],
    "Space": ["área"],
}
GEOM_CLASSES = ("IfcWall", "IfcSlab", "IfcBeam", "IfcColumn", "IfcFooting", "IfcRoof", "IfcCovering",
                "IfcMember", "IfcPlate", "IfcPile", "IfcStair", "IfcRamp", "IfcSpace")


class IfcReadError(Exception):
    """Arquivo IFC inválido, corrompido ou de versão não suportada."""


class Cancelled(Exception):
    pass


def _clean(v):
    """Converte valores do IfcOpenShell em JSON simples."""
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items() if k != "id"}
    return str(v)


def _category(cls: str) -> str | None:
    for key in EXPECTED:
        if cls.startswith("Ifc" + key):
            return key
    return None


def open_ifc(path: Path):
    import ifcopenshell
    with open(path, "rb") as fh:  # lê só o começo e o fim (arquivos podem ter centenas de MB)
        head = fh.read(64)
        fh.seek(0, 2)
        fh.seek(max(0, fh.tell() - 1024))
        tail = fh.read()
    if b"ISO-10303-21" not in head:
        raise IfcReadError("O arquivo não é um IFC em formato STEP (.ifc). IFCZIP e ifcXML ainda não são aceitos.")
    if b"END-ISO-10303-21" not in tail:
        # o IfcOpenShell é tolerante e leria só a parte existente: o inventário sairia incompleto sem aviso
        raise IfcReadError("O arquivo IFC está incompleto (falta o final do arquivo). "
                           "Provavelmente o envio ou a exportação foi interrompido — exporte novamente.")
    try:
        f = ifcopenshell.open(str(path))
    except Exception as e:
        if "Unsupported schema" in str(e):
            raise IfcReadError(f"Versão IFC não suportada ({e}). Aceitas: IFC2X3, IFC4, IFC4X3.") from e
        raise IfcReadError(f"Não foi possível abrir o IFC (arquivo corrompido ou incompleto): {e}") from e
    schema = (f.schema or "").upper()
    if not schema.startswith(SUPPORTED_SCHEMAS):
        raise IfcReadError(f"Versão IFC «{f.schema}» não suportada. Aceitas: IFC2X3, IFC4, IFC4X3.")
    return f


def _header(f) -> dict:
    h = {"schema": f.schema, "schema_identifier": getattr(f, "schema_identifier", f.schema)}
    try:
        fn = f.header.file_name
        h["application"] = fn.preprocessor_version or ""
        h["originating_system"] = fn.originating_system or ""
        h["timestamp"] = fn.time_stamp or ""
        h["view"] = " ".join(f.header.file_description.description or [])
    except Exception:
        pass
    proj = f.by_type("IfcProject")
    h["project_name"] = (proj[0].Name or proj[0].LongName or "") if proj else ""
    return h


def _materials(element, ue, lscale) -> tuple[list[dict], dict | None]:
    m = ue.get_material(element, should_skip_usage=True)
    if m is None:
        return [], None
    out, mset = [], None
    if m.is_a("IfcMaterialLayerSet"):
        total = 0.0
        for layer in m.MaterialLayers or []:
            t = (layer.LayerThickness or 0) * lscale
            total += t
            mat = layer.Material
            out.append({"name": mat.Name if mat else None, "category": getattr(mat, "Category", None) if mat else None,
                        "thickness_m": round(t, 6), "source": "camada (IfcMaterialLayer)"})
        mset = {"kind": "camadas", "name": getattr(m, "LayerSetName", None), "total_thickness_m": round(total, 6)}
    elif m.is_a("IfcMaterialProfileSet"):
        for p in m.MaterialProfiles or []:
            mat = p.Material
            out.append({"name": mat.Name if mat else None, "category": getattr(mat, "Category", None) if mat else None,
                        "profile": getattr(p.Profile, "ProfileName", None) if p.Profile else None,
                        "source": "perfil (IfcMaterialProfile)"})
        mset = {"kind": "perfis", "name": m.Name}
    elif m.is_a("IfcMaterialConstituentSet"):
        for c in m.MaterialConstituents or []:
            mat = c.Material
            out.append({"name": mat.Name if mat else None, "category": getattr(mat, "Category", None) if mat else None,
                        "part": c.Name, "source": "constituinte (IfcMaterialConstituent)"})
        mset = {"kind": "constituintes", "name": m.Name}
    elif m.is_a("IfcMaterialList"):
        for mat in m.Materials or []:
            out.append({"name": mat.Name, "category": None, "source": "lista (IfcMaterialList)"})
        mset = {"kind": "lista", "name": None}
    elif m.is_a("IfcMaterial"):
        out.append({"name": m.Name, "category": getattr(m, "Category", None), "source": "material (IfcMaterial)"})
    return out, mset


def _quantities(element, scales) -> list[dict]:
    out = []
    for rel in getattr(element, "IsDefinedBy", None) or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        d = rel.RelatingPropertyDefinition
        if not d.is_a("IfcElementQuantity"):
            continue
        for q in d.Quantities or []:
            kind = QTY_KIND.get(q.is_a())
            if not kind:
                continue
            attr, utype, sym = kind
            val = getattr(q, attr, None)
            if val is None:
                continue
            unit_note = None
            if getattr(q, "Unit", None) is not None:
                unit_note = "unidade própria na quantidade — valor sem conversão"
                factor, sym = 1.0, "(ver IFC)"
            else:
                factor = scales.get(utype, 1.0) if utype else 1.0
            out.append({"name": q.Name, "value": _clean(float(val) * factor), "unit": sym,
                        "source": d.Name, "method": "explicito", "note": unit_note})
    return out


def read_ifc(path: Path, progress: Callable[[float, str], None] | None = None,
             should_cancel: Callable[[], bool] | None = None,
             geometry: bool = True, geometry_seconds: float = 120.0) -> dict:
    """Lê o IFC e devolve {header, units, storeys, elements, warnings, geometry}."""
    import ifcopenshell.util.classification as uclass
    import ifcopenshell.util.element as ue
    import ifcopenshell.util.system as usys
    import ifcopenshell.util.unit as uu

    progress = progress or (lambda p, m: None)
    should_cancel = should_cancel or (lambda: False)
    t0 = time.time()
    progress(0.02, "Abrindo o arquivo IFC…")
    f = open_ifc(path)
    header = _header(f)
    scales = {u: uu.calculate_unit_scale(f, u) for u in ("LENGTHUNIT", "AREAUNIT", "VOLUMEUNIT", "MASSUNIT")}
    lscale = scales["LENGTHUNIT"]
    warnings: list[str] = []

    storeys = []
    for s in f.by_type("IfcBuildingStorey"):
        storeys.append({"global_id": s.GlobalId, "name": s.Name or s.LongName or "(sem nome)",
                        "elevation_m": _clean((s.Elevation or 0) * lscale) if s.Elevation is not None else None})
    storeys.sort(key=lambda s: (s["elevation_m"] is None, s["elevation_m"] or 0))

    products = [p for p in f.by_type("IfcProduct")
                if (p.is_a("IfcElement") or p.is_a("IfcSpace")) and p.is_a() not in AUXILIARY
                and not p.is_a("IfcFeatureElementSubtraction")]
    auxiliary = sum(1 for p in f.by_type("IfcProduct") if p.is_a() in AUXILIARY)
    n = len(products)
    elements: list[dict] = []
    by_step: dict[int, dict] = {}
    read_errors = 0
    for i, e in enumerate(products):
        if i % 200 == 0:
            if should_cancel():
                raise Cancelled()
            progress(0.05 + 0.65 * i / max(n, 1), f"Lendo elementos ({i} de {n})…")
        try:
            el = _read_element(e, ue, uclass, usys, scales, lscale)
        except Exception as ex:  # um elemento ruim não derruba o modelo inteiro
            read_errors += 1
            el = {"global_id": getattr(e, "GlobalId", None), "ifc_class": e.is_a(), "name": getattr(e, "Name", None),
                  "read_error": f"{type(ex).__name__}: {ex}", "quantities": [], "materials": [], "psets": {}}
            log.warning("Erro lendo %s: %s", e, ex)
        elements.append(el)
        by_step[e.id()] = el
    if read_errors:
        warnings.append(f"{read_errors} elemento(s) com erro de leitura (lidos parcialmente).")

    geom_info = {"status": "não executado", "seconds": 0, "computed": 0, "failed": 0}
    if geometry:
        progress(0.72, "Calculando quantidades pela geometria 3D…")
        geom_info = _geometry(f, products, by_step, geometry_seconds, should_cancel, progress)
        if geom_info["status"] == "interrompido":
            warnings.append(f"Cálculo geométrico interrompido após {geometry_seconds:.0f} s "
                            f"({geom_info['computed']} elementos calculados).")

    progress(0.95, "Classificando e conferindo informações…")
    for el in elements:
        if "read_error" not in el:
            el.update(classify(el))
            el["checks"], el["missing"] = _checks(el)
        else:
            el.update({"discipline": "Pendente", "confidence": "baixa", "reasons": ["erro de leitura"],
                       "suggestion": None, "checks": [], "missing": []})
    return {
        "header": header,
        "units": {"length_scale_to_m": lscale, **{k.lower(): v for k, v in scales.items()}},
        "storeys": storeys,
        "elements": elements,
        "auxiliary_count": auxiliary,
        "warnings": warnings,
        "geometry": geom_info,
        "parse_seconds": round(time.time() - t0, 2),
    }


def _read_element(e, ue, uclass, usys, scales, lscale) -> dict:
    t = ue.get_type(e)
    storey = ue.get_container(e, ifc_class="IfcBuildingStorey")
    if storey is None and e.is_a("IfcSpace"):
        parent = ue.get_aggregate(e)
        storey = parent if parent is not None and parent.is_a("IfcBuildingStorey") else None
    psets = ue.get_psets(e, psets_only=True)
    materials, mset = _materials(e, ue, lscale)
    quantities = _quantities(e, scales)
    if mset and mset.get("total_thickness_m"):
        quantities.append({"name": "Espessura (camadas de material)", "value": mset["total_thickness_m"],
                           "unit": "m", "source": "IfcMaterialLayerSet", "method": "explicito",
                           "note": "soma das espessuras das camadas"})
    for attr in ("OverallHeight", "OverallWidth"):
        v = getattr(e, attr, None) if hasattr(e, attr) else None
        if v is not None:
            quantities.append({"name": attr, "value": _clean(float(v) * lscale), "unit": "m",
                               "source": f"atributo {e.is_a()}.{attr}", "method": "atributo", "note": None})
    systems = []
    try:
        for s in usys.get_element_systems(e):
            systems.append({"name": s.Name, "predefined": getattr(s, "PredefinedType", None), "class": s.is_a()})
    except Exception:
        pass
    classif = []
    try:
        for r in uclass.get_references(e):
            src = getattr(r, "ReferencedSource", None)
            classif.append({"code": getattr(r, "Identification", None) or getattr(r, "ItemReference", None),
                            "name": r.Name, "system": getattr(src, "Name", None) if src else None})
    except Exception:
        pass
    return {
        "global_id": e.GlobalId,
        "ifc_class": e.is_a(),
        "predefined_type": _clean(getattr(e, "PredefinedType", None)) if hasattr(e, "PredefinedType") else None,
        "name": e.Name,
        "description": e.Description,
        "object_type": getattr(e, "ObjectType", None),
        "tag": getattr(e, "Tag", None),
        "long_name": getattr(e, "LongName", None),
        "type_name": t.Name if t else None,
        "type_class": t.is_a() if t else None,
        "storey": storey.Name if storey else None,
        "systems": systems,
        "classification": classif,
        "materials": materials,
        "material_set": mset,
        "psets": _clean(psets),
        "quantities": quantities,
        "has_geometry": bool(getattr(e, "Representation", None)),
    }


def _geometry(f, products, by_step, max_seconds, should_cancel, progress) -> dict:
    """Volume/áreas pela malha 3D só para elementos SEM quantidade explícita equivalente."""
    import ifcopenshell.geom
    import ifcopenshell.util.shape as us

    todo = []
    for p in products:
        el = by_step.get(p.id())
        if not el or not el.get("has_geometry") or not p.is_a().startswith(GEOM_CLASSES):
            continue
        names = {q["name"] for q in el["quantities"]}
        if p.is_a("IfcSpace"):
            if not names & INFO_KEYS["área"]:
                todo.append(p)
        elif not names & INFO_KEYS["volume"]:
            todo.append(p)
    info = {"status": "concluído", "seconds": 0, "computed": 0, "failed": 0, "candidates": len(todo),
            "method": "Malha triangulada do sólido (IfcOpenShell geom, coordenadas em metros). "
                      "Não usa a caixa envolvente. Aproximação para conferência, não quantitativo executivo."}
    if not todo:
        info["status"] = "nada a calcular"
        return info
    t0 = time.time()
    settings = ifcopenshell.geom.settings()
    try:
        it = ifcopenshell.geom.iterator(settings, f, 2, include=todo)
        ok = it.initialize()
    except Exception as e:
        info.update(status="falhou", error=str(e))
        return info
    done = 0
    while ok:
        if should_cancel():
            raise Cancelled()
        if time.time() - t0 > max_seconds:
            info["status"] = "interrompido"
            break
        try:
            shape = it.get()
            el = by_step.get(shape.id)
            g = shape.geometry
            if el is not None:
                cls = el["ifc_class"]
                note = info["method"]
                vol = None if cls == "IfcSpace" else us.get_volume(g)
                if cls == "IfcSpace":
                    a = us.get_footprint_area(g)
                    if a:
                        el["quantities"].append({"name": "Área de piso (malha 3D)", "value": round(a, 6),
                                                 "unit": "m²", "source": "geometria", "method": "geometrico",
                                                 "note": note + " Projeção do ambiente em planta."})
                if vol and vol > 0:
                    el["quantities"].append({"name": "Volume (malha 3D)", "value": round(vol, 6), "unit": "m³",
                                             "source": "geometria", "method": "geometrico", "note": note})
                if cls.startswith("IfcWall"):
                    a = us.get_side_area(g)
                    if a:
                        el["quantities"].append({"name": "Área lateral (malha 3D)", "value": round(a, 6),
                                                 "unit": "m²", "source": "geometria", "method": "geometrico",
                                                 "note": note + " Área de uma face lateral (eixo local)."})
                elif cls.startswith(("IfcSlab", "IfcRoof", "IfcCovering")):
                    a = us.get_footprint_area(g)
                    if a:
                        el["quantities"].append({"name": "Área de projeção (malha 3D)", "value": round(a, 6),
                                                 "unit": "m²", "source": "geometria", "method": "geometrico",
                                                 "note": note + " Projeção em planta."})
                info["computed"] += 1
        except Exception:
            info["failed"] += 1
        done += 1
        if done % 50 == 0:
            progress(0.72 + 0.22 * done / max(len(todo), 1), f"Geometria ({done} de {len(todo)})…")
        ok = it.next()
    info["seconds"] = round(time.time() - t0, 2)
    return info


def _checks(el: dict) -> tuple[list[dict], list[str]]:
    cat = _category(el["ifc_class"])
    wanted = ["pavimento"] + (EXPECTED.get(cat, []) if cat else [])
    checks, missing = [], []
    for info in wanted:
        if info == "pavimento":
            ok = bool(el.get("storey"))
            checks.append({"info": info, "status": "explícito" if ok else "não encontrado", "value": el.get("storey")})
        elif info == "material":
            ok = bool(el.get("materials"))
            checks.append({"info": info, "status": "explícito" if ok else "não encontrado",
                           "value": ", ".join(dict.fromkeys(m["name"] for m in el["materials"] if m.get("name"))) or None})
        else:
            keys = set(INFO_KEYS[info])
            if info == "espessura" and cat in ("Slab", "Roof", "Covering"):
                keys.add("Depth")  # Qto_SlabBaseQuantities usa Depth como espessura em vários exportadores
            found = [q for q in el["quantities"] if q["name"] in keys]
            explicit = [q for q in found if q["method"] in ("explicito", "atributo")]
            q = (explicit or found or [None])[0]
            status = ("explícito" if explicit else "calculado" if found else "não encontrado")
            checks.append({"info": info, "status": status,
                           "value": f"{q['value']:g} {q['unit']}" if q and isinstance(q["value"], (int, float)) else None,
                           "source": q["name"] if q else None})
            ok = bool(found)
        if not ok:
            missing.append(info)
    return checks, missing
