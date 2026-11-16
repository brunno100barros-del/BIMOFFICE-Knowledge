"""Gera o IFC do PROJETO EXEMPLO (fictício): Escola SENAI — Bloco B de salas de aula.

Dados inventados para DEMONSTRAÇÃO do BIMOFFICE Knowledge — não representam obra real.
Contém, de propósito, algumas lacunas (vigas sem volume, bancada genérica sem classificação,
parede de drywall sem quantitativos) para demonstrar a detecção de pendências.
Todos os elementos têm forma 3D simples (sólidos) em posições coerentes, para o visualizador 3D;
onde o IFC não traz quantidade, o leitor a calcula pela geometria e marca "a conferir".

Uso:  python scripts/exemplo/gerar_ifc_exemplo.py [saida.ifc]
"""
from __future__ import annotations

import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.aggregate as agg
import ifcopenshell.api.context as ctx
import ifcopenshell.api.geometry as geo
import ifcopenshell.api.material as mat
import ifcopenshell.api.owner.settings as owner_settings
import ifcopenshell.api.project as proj
import ifcopenshell.api.pset as pset
import ifcopenshell.api.root as root
import ifcopenshell.api.spatial as spatial
import ifcopenshell.api.style as style
import ifcopenshell.api.system as system
import ifcopenshell.api.type as typ
import ifcopenshell.api.unit as unit
import numpy as np

OUT = Path(__file__).resolve().parents[2] / "exemplos" / "projeto_exemplo" / "Escola_SENAI_Bloco_B_EXEMPLO.ifc"


def main(out: Path = OUT) -> Path:
    f = proj.create_file(version="IFC4")
    person = f.createIfcPerson(FamilyName="Exemplo")
    org = f.createIfcOrganization(Name="SENAI/RO - Setor BIM Office (exemplo)")
    user = f.createIfcPersonAndOrganization(person, org)
    app = f.createIfcApplication(org, "0.4", "BIMOFFICE Knowledge - gerador de exemplo", "bimoffice-exemplo")
    owner_settings.get_user = lambda _f: user
    owner_settings.get_application = lambda _f: app

    def mk(cls, name, **attrs):
        e = root.create_entity(f, ifc_class=cls, name=name)
        for k, v in attrs.items():
            setattr(e, k, v)
        return e

    def ps(e, name, props):
        p = pset.add_pset(f, product=e, name=name)
        pset.edit_pset(f, pset=p, properties=props)

    def qto(e, name, props):
        q = pset.add_qto(f, product=e, name=name)
        pset.edit_qto(f, qto=q, properties=props)

    project = mk("IfcProject", "Escola SENAI - Bloco B (EXEMPLO FICTÍCIO)")
    unit.assign_unit(f, length={"is_metric": True, "raw": "METERS"},
                     area={"is_metric": True, "raw": "SQUARE_METERS"},
                     volume={"is_metric": True, "raw": "CUBIC_METERS"})
    model = ctx.add_context(f, context_type="Model")
    body = ctx.add_context(f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model)

    site = mk("IfcSite", "Terreno - Unidade SENAI (exemplo)")
    building = mk("IfcBuilding", "Bloco B - Salas de aula")
    terreo = mk("IfcBuildingStorey", "Térreo", Elevation=0.0)
    superior = mk("IfcBuildingStorey", "Pavimento Superior", Elevation=3.40)
    cobertura = mk("IfcBuildingStorey", "Cobertura", Elevation=6.80)
    agg.assign_object(f, products=[site], relating_object=project)
    agg.assign_object(f, products=[building], relating_object=site)
    agg.assign_object(f, products=[terreo, superior, cobertura], relating_object=building)

    def put(items, storey):
        spatial.assign_container(f, products=items, relating_structure=storey)

    # ---------------- cores de apresentação (IfcSurfaceStyle), como os programas de modelagem exportam
    COLORS = {  # classe[:PredefinedType] -> (R, G, B, transparência)
        "IfcWall": (0.93, 0.90, 0.84, 0), "IfcColumn": (0.66, 0.67, 0.69, 0), "IfcBeam": (0.66, 0.67, 0.69, 0),
        "IfcFooting": (0.55, 0.56, 0.58, 0), "IfcSlab": (0.74, 0.75, 0.77, 0), "IfcStair": (0.70, 0.71, 0.73, 0),
        "IfcRailing": (0.25, 0.27, 0.30, 0), "IfcMember": (0.30, 0.38, 0.50, 0), "steel": (0.30, 0.38, 0.50, 0),
        "IfcCovering:ROOFING": (0.62, 0.70, 0.78, 0.35), "IfcCovering:FLOORING": (0.86, 0.80, 0.70, 0),
        "IfcCovering:CEILING": (0.98, 0.98, 0.98, 0.55), "IfcCovering:CLADDING": (0.82, 0.90, 0.95, 0),
        "IfcDoor": (0.62, 0.42, 0.25, 0), "IfcWindow": (0.45, 0.68, 0.88, 0.45), "IfcSpace": (0.40, 0.75, 0.55, 0.75),
        "IfcPipeSegment": (0.10, 0.55, 0.85, 0), "IfcPipeSegment:esgoto": (0.55, 0.38, 0.20, 0),
        "IfcSanitaryTerminal": (0.97, 0.97, 0.97, 0), "IfcWasteTerminal": (0.40, 0.40, 0.42, 0), "IfcTank": (0.15, 0.40, 0.75, 0),
        "IfcLightFixture": (1.0, 0.92, 0.55, 0), "IfcOutlet": (0.95, 0.75, 0.10, 0),
        "IfcElectricDistributionBoard": (0.90, 0.55, 0.10, 0), "IfcCableCarrierSegment": (0.95, 0.75, 0.10, 0),
        "IfcUnitaryEquipment": (0.92, 0.94, 0.96, 0), "IfcFan": (0.60, 0.65, 0.70, 0),
        "IfcBuildingElementProxy": (0.80, 0.30, 0.30, 0),
    }
    _styles = {}

    def color_of(e):
        k = e.is_a()
        pt = getattr(e, "PredefinedType", None)
        if k == "IfcPipeSegment" and "esgoto" in (e.Name or ""):
            return COLORS["IfcPipeSegment:esgoto"]
        if k == "IfcBeam" and "metálica" in (e.Name or ""):
            return COLORS["steel"]
        return COLORS.get(f"{k}:{pt}") or COLORS.get(k) or (0.8, 0.8, 0.8, 0)

    def paint(e, r):
        c = color_of(e)
        if c not in _styles:
            st = style.add_style(f, name=f"Cor {len(_styles) + 1}")
            style.add_surface_style(f, style=st, ifc_class="IfcSurfaceStyleShading", attributes={
                "SurfaceColour": {"Name": None, "Red": c[0], "Green": c[1], "Blue": c[2]}, "Transparency": c[3]})
            _styles[c] = st
        style.assign_representation_styles(f, shape_representation=r, styles=[_styles[c]])

    # ---------------- formas 3D simples (sólidos fechados; coordenadas em metros, globais)
    FACES = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]

    def box(x0, y0, z0, x1, y1, z1):
        return [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]

    def solid(e, *hexas):
        """Forma do elemento = um ou mais hexaedros (8 vértices na ordem de box())."""
        ox = min(v[0] for h in hexas for v in h)
        oy = min(v[1] for h in hexas for v in h)
        oz = min(v[2] for h in hexas for v in h)
        verts = [[(v[0] - ox, v[1] - oy, v[2] - oz) for v in h] for h in hexas]
        r = geo.add_mesh_representation(f, context=body, vertices=verts, faces=[FACES] * len(hexas))
        geo.assign_representation(f, product=e, representation=r)
        paint(e, r)
        m = np.eye(4)
        m[0, 3], m[1, 3], m[2, 3] = ox, oy, oz
        geo.edit_object_placement(f, product=e, matrix=m)
        return e

    def slab_between(x0, x1, ya, za, yb, zb, t):
        """Placa inclinada (telhado/escada): de (ya, za) a (yb, zb) ao longo de y, espessura t."""
        return [(x0, ya, za), (x1, ya, za), (x1, yb, zb), (x0, yb, zb),
                (x0, ya, za + t), (x1, ya, za + t), (x1, yb, zb + t), (x0, yb, zb + t)]

    M = {n: mat.add_material(f, name=n, category=c) for n, c in [
        ("Argamassa de revestimento", "plaster"), ("Bloco cerâmico vazado 14x19x29", "block"),
        ("Bloco cerâmico vazado 9x19x29", "block"), ("Chapa de gesso acartonado", "gypsum"),
        ("Montante de aço galvanizado", "steel"), ("Concreto C30", "concrete"),
        ("Aço ASTM A36", "steel"), ("Aço ASTM A572 Gr.50", "steel"),
        ("Telha termoacústica aço galvanizado + PIR 30 mm", "steel"),
        ("Porcelanato 60x60 cm", "ceramic"), ("Piso cerâmico antiderrapante 45x45 cm", "ceramic"),
        ("Revestimento cerâmico 30x60 cm", "ceramic"), ("Gesso acartonado (forro)", "gypsum"),
        ("Madeira (porta semi-oca)", "wood"), ("Alumínio anodizado", "aluminium"),
        ("Vidro temperado 6 mm", "glass"), ("PVC soldável", "plastic"), ("PVC esgoto série normal", "plastic"),
        ("Louça sanitária", "ceramic"), ("Polietileno", "plastic"), ("Granito", "stone"),
    ]}

    def layerset(name, layers):
        ls = mat.add_material_set(f, name=name, set_type="IfcMaterialLayerSet")
        for m, t in layers:
            lay = mat.add_layer(f, layer_set=ls, material=M[m])
            lay.LayerThickness = t
        return ls

    ext = layerset("Alvenaria externa 19 cm", [("Argamassa de revestimento", 0.025),
                                                ("Bloco cerâmico vazado 14x19x29", 0.14),
                                                ("Argamassa de revestimento", 0.025)])
    inn = layerset("Alvenaria interna 14 cm", [("Argamassa de revestimento", 0.025),
                                               ("Bloco cerâmico vazado 9x19x29", 0.09),
                                               ("Argamassa de revestimento", 0.025)])
    dry = layerset("Divisória drywall 9,5 cm", [("Chapa de gesso acartonado", 0.0125),
                                                ("Montante de aço galvanizado", 0.07),
                                                ("Chapa de gesso acartonado", 0.0125)])

    def wall(name, storey, lset, length, external, x=0.0, y=0.0, with_qto=True, fire=None, along_y=False):
        thick = sum(l.LayerThickness for l in lset.MaterialLayers)
        h = 3.40
        w = mk("IfcWall", name)
        rep = geo.add_wall_representation(f, context=body, length=length, height=h, thickness=thick)
        geo.assign_representation(f, product=w, representation=rep)
        paint(w, rep)
        m = np.eye(4)
        if along_y:  # eixo local x -> global y; a espessura fica para -x
            m[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        m[0, 3], m[1, 3], m[2, 3] = x, y, storey.Elevation
        geo.edit_object_placement(f, product=w, matrix=m)
        mat.assign_material(f, products=[w], type="IfcMaterialLayerSetUsage", material=lset)
        props = {"IsExternal": external, "LoadBearing": False}
        if fire:
            props["FireRating"] = fire
        ps(w, "Pset_WallCommon", props)
        if with_qto:
            qto(w, "Qto_WallBaseQuantities", {"Length": length, "Height": h, "Width": round(thick, 4),
                                               "NetSideArea": round(length * h, 3),
                                               "NetVolume": round(length * h * thick, 4)})
        put([w], storey)
        return w

    for st, tag in ((terreo, "T"), (superior, "S")):
        # planta 24 x 12 m: salas ao norte (y 0-8), circulação ao sul (y 8-12), sanitários a leste no térreo
        wall(f"Parede externa {tag}-01 (fachada norte)", st, ext, 24.0, True, 0, 0, fire="EI 60")
        wall(f"Parede externa {tag}-02 (fachada leste)", st, ext, 12.0, True, 24, 0, fire="EI 60", along_y=True)
        wall(f"Parede externa {tag}-03 (fachada sul)", st, ext, 24.0, True, 0, 11.81, fire="EI 60")
        wall(f"Parede externa {tag}-04 (fachada oeste)", st, ext, 12.0, True, 0.19, 0, fire="EI 60", along_y=True)
        for i in range(3):  # parede da circulação (y = 8), em 3 trechos de 8 m
            wall(f"Parede interna {tag}-{i + 5:02d}", st, inn, 8.0, False, 8.0 * i, 7.93)
    wall("Divisória sanitários T-08", terreo, dry, 4.0, False, 20, 4)
    wall("Divisória sanitários T-09 (sem quantitativos no IFC)", terreo, dry, 4.0, False, 20.05, 4, with_qto=False, along_y=True)

    # ---------------- estrutura de concreto
    COLS = [(x, y) for y in (0.0, 11.7) for x in (0.0, 7.85, 15.85, 23.7)]  # pilares 30x30 cm
    for i in range(8):
        s = mk("IfcFooting", f"Sapata S{i + 1}", PredefinedType="PAD_FOOTING")
        cx, cy = COLS[i][0] + 0.15, COLS[i][1] + 0.15
        solid(s, box(cx - 0.8, cy - 0.8, -1.5, cx + 0.8, cy + 0.8, -1.0))
        mat.assign_material(f, products=[s], type="IfcMaterial", material=M["Concreto C30"])
        qto(s, "Qto_FootingBaseQuantities", {"Length": 1.6, "Width": 1.6, "Height": 0.5, "NetVolume": 1.28})
        put([s], terreo)
    for st in (terreo, superior):
        for i in range(8):
            c = mk("IfcColumn", f"Pilar P{i + 1} ({st.Name})")
            x, y = COLS[i]
            solid(c, box(x, y, st.Elevation, x + 0.3, y + 0.3, st.Elevation + 3.4))
            mat.assign_material(f, products=[c], type="IfcMaterial", material=M["Concreto C30"])
            qto(c, "Qto_ColumnBaseQuantities", {"Length": 3.4, "CrossSectionArea": 0.09, "NetVolume": 0.306})
            ps(c, "Pset_ColumnCommon", {"LoadBearing": True})
            put([c], st)
        for i in range(6):  # vigas SEM volume no IFC (lacuna proposital)
            b = mk("IfcBeam", f"Viga V{i + 1} 20x50 ({st.Name})")
            y = 0.05 if i < 3 else 11.75
            x0 = 8.0 * (i % 3)
            z1 = st.Elevation + 3.4 - 0.12
            solid(b, box(x0, y, z1 - 0.5, x0 + 8.0, y + 0.2, z1))
            mat.assign_material(f, products=[b], type="IfcMaterial", material=M["Concreto C30"])
            ps(b, "Pset_BeamCommon", {"LoadBearing": True})
            put([b], st)
    for st, nome, area in ((superior, "Laje do Pavimento Superior", 288.0), (cobertura, "Laje de forro da cobertura", 288.0)):
        lj = mk("IfcSlab", nome, PredefinedType="FLOOR")
        solid(lj, box(0, 0, st.Elevation - 0.12, 24, 12, st.Elevation))
        mat.assign_material(f, products=[lj], type="IfcMaterial", material=M["Concreto C30"])
        ps(lj, "Pset_SlabCommon", {"LoadBearing": True, "IsExternal": False})
        qto(lj, "Qto_SlabBaseQuantities", {"Width": 0.12, "GrossArea": area, "NetArea": area, "NetVolume": area * 0.12})
        put([lj], st)
    esc = mk("IfcStair", "Escada de concreto armado (2 lances)", PredefinedType="HALF_TURN_STAIR")
    # dois lances na circulação (x 1-2,2 e 2,2-3,4), patamar a meia altura junto à fachada sul
    solid(esc, slab_between(1.0, 2.2, 8.2, 0.0, 10.4, 1.7, 0.18), box(1.0, 10.4, 1.52, 3.4, 11.8, 1.7),
          slab_between(2.2, 3.4, 10.4, 1.7, 8.2, 3.4, 0.18))
    mat.assign_material(f, products=[esc], type="IfcMaterial", material=M["Concreto C30"])
    gc = mk("IfcRailing", "Guarda-corpo metálico h=1,10 m", PredefinedType="GUARDRAIL")
    solid(gc, box(3.4, 8.1, 3.4, 13.0, 8.15, 4.5))
    mat.assign_material(f, products=[gc], type="IfcMaterial", material=M["Aço ASTM A36"])
    qto(gc, "Qto_RailingBaseQuantities", {"Length": 9.6})
    put([esc, gc], terreo)

    # ---------------- cobertura metálica
    for i in range(6):
        t = mk("IfcBeam", f"Tesoura metálica TS{i + 1}")
        x = 0.2 + i * 4.66
        solid(t, slab_between(x, x + 0.15, 0.0, 6.8, 6.0, 8.0, 0.25), slab_between(x, x + 0.15, 6.0, 8.0, 12.0, 6.8, 0.25),
              box(x, 0.0, 6.8, x + 0.15, 12.0, 6.95))
        mat.assign_material(f, products=[t], type="IfcMaterial", material=M["Aço ASTM A572 Gr.50"])
        put([t], cobertura)
    for i in range(10):
        t = mk("IfcMember", f"Terça metálica perfil U 150x60 - T{i + 1}", PredefinedType="PURLIN")
        y = (0.6, 2.4, 4.2, 7.8, 9.6)[i // 2]
        z = 6.8 + 0.25 + 1.2 * (1 - abs(y + 0.03 - 6.0) / 6.0)
        x0 = 0.0 if i % 2 == 0 else 12.0
        solid(t, box(x0, y, z, x0 + 12.0, y + 0.06, z + 0.15))
        mat.assign_material(f, products=[t], type="IfcMaterial", material=M["Aço ASTM A36"])
        qto(t, "Qto_MemberBaseQuantities", {"Length": 12.0})
        put([t], cobertura)
    telhado = mk("IfcRoof", "Cobertura em duas águas", PredefinedType="GABLE_ROOF")
    telha = mk("IfcCovering", "Telha termoacústica trapezoidal (sanduíche 30 mm)", PredefinedType="ROOFING")
    mat.assign_material(f, products=[telha], type="IfcMaterial", material=M["Telha termoacústica aço galvanizado + PIR 30 mm"])
    solid(telha, slab_between(-0.4, 24.4, -0.5, 7.15, 6.0, 8.45, 0.03), slab_between(-0.4, 24.4, 6.0, 8.45, 12.5, 7.15, 0.03))
    qto(telha, "Qto_CoveringBaseQuantities", {"Width": 0.03, "NetArea": 320.0})
    ps(telha, "Pset_CoveringCommon", {"IsExternal": True})
    put([telhado, telha], cobertura)

    # ---------------- acabamentos
    def cov(name, ptype, material, area, storey, extra=None, shape=()):
        c = mk("IfcCovering", name, PredefinedType=ptype)
        if shape:
            solid(c, *shape)
        mat.assign_material(f, products=[c], type="IfcMaterial", material=M[material])
        q = {"NetArea": area}
        if extra:
            q.update(extra)
        qto(c, "Qto_CoveringBaseQuantities", q)
        put([c], storey)
    cov("Piso porcelanato - salas do térreo", "FLOORING", "Porcelanato 60x60 cm", 216.0, terreo,
        shape=[box(0.19, 0.19, 0.0, 18.0, 11.81, 0.02)])
    cov("Piso porcelanato - salas do superior", "FLOORING", "Porcelanato 60x60 cm", 216.0, superior,
        shape=[box(0.19, 0.19, 3.40, 23.81, 11.81, 3.42)])
    cov("Piso antiderrapante - sanitários", "FLOORING", "Piso cerâmico antiderrapante 45x45 cm", 36.0, terreo,
        shape=[box(18.0, 0.19, 0.0, 23.81, 7.93, 0.02)])
    cov("Revestimento de parede - sanitários (até o teto)", "CLADDING", "Revestimento cerâmico 30x60 cm", 92.0, terreo,
        shape=[box(18.0, 0.19, 0.02, 23.81, 0.2, 2.8), box(23.8, 0.19, 0.02, 23.81, 7.93, 2.8),
               box(18.0, 7.92, 0.02, 23.81, 7.93, 2.8)])
    cov("Forro de gesso acartonado - térreo", "CEILING", "Gesso acartonado (forro)", 252.0, terreo,
        shape=[box(0.19, 0.19, 2.80, 23.81, 11.81, 2.8125)])
    cov("Forro de gesso acartonado - superior", "CEILING", "Gesso acartonado (forro)", 252.0, superior,
        shape=[box(0.19, 0.19, 6.20, 23.81, 11.81, 6.2125)])

    # ---------------- esquadrias (tipos)
    def door_type(name, w, h, material):
        t = mk("IfcDoorType", name, PredefinedType="DOOR", OperationType="SINGLE_SWING_LEFT")
        mat.assign_material(f, products=[t], type="IfcMaterial", material=M[material])
        return t, w, h

    def add_doors(dt, n, storey, prefix, xs, y0=7.9, y1=8.1, along_y=False):
        t, w, h = dt
        objs = [mk("IfcDoor", f"{prefix}{i + 1}", OverallWidth=w, OverallHeight=h) for i in range(n)]
        for o, x in zip(objs, xs):
            z = storey.Elevation
            solid(o, box(y0, x, z, y1, x + w, z + h) if along_y else box(x, y0, z, x + w, y1, z + h))
        typ.assign_type(f, related_objects=objs, relating_type=t)
        put(objs, storey)

    pm = door_type("Porta de madeira semi-oca 90x210 cm", 0.9, 2.1, "Madeira (porta semi-oca)")
    pa = door_type("Porta de alumínio veneziana 80x210 cm", 0.8, 2.1, "Alumínio anodizado")
    pp = door_type("Porta acessível 90x210 cm com barra horizontal", 0.9, 2.1, "Madeira (porta semi-oca)")
    add_doors(pm, 3, terreo, "PM-T", [2.5, 8.5, 14.5])                    # salas (parede da circulação)
    add_doors(pm, 3, superior, "PM-S", [2.5, 8.5, 14.5])
    add_doors(pa, 2, terreo, "PA-T", [19.0, 22.0])                          # sanitários
    add_doors(pp, 2, terreo, "PNE-T", [11.1, 12.0], y0=11.78, y1=12.02)     # acesso principal (fachada sul)
    jt = mk("IfcWindowType", "Janela de alumínio de correr 200x120 cm, 2 folhas", PredefinedType="WINDOW",
            PartitioningType="DOUBLE_PANEL_VERTICAL")
    ws = mat.add_material_set(f, name="Alumínio + vidro", set_type="IfcMaterialConstituentSet")
    mat.add_constituent(f, constituent_set=ws, material=M["Alumínio anodizado"]).Name = "Caixilho"
    mat.add_constituent(f, constituent_set=ws, material=M["Vidro temperado 6 mm"]).Name = "Vidro"
    mat.assign_material(f, products=[jt], type="IfcMaterialConstituentSet", material=ws)
    for st, tag in ((terreo, "T"), (superior, "S")):
        js = [mk("IfcWindow", f"J{tag}{i + 1}", OverallWidth=2.0, OverallHeight=1.2) for i in range(6)]
        for i, j in enumerate(js):  # fachada norte, peitoril 1,00 m
            x = 1.0 + 4.0 * i
            solid(j, box(x, -0.02, st.Elevation + 1.0, x + 2.0, 0.21, st.Elevation + 2.2))
        typ.assign_type(f, related_objects=js, relating_type=jt)
        put(js, st)

    # ---------------- ambientes
    for st, salas, w in ((terreo, ["Sala de aula 01", "Sala de aula 02", "Sala de aula 03"], 6.0),
                         (superior, ["Sala de aula 04", "Sala de aula 05", "Laboratório de informática"], 8.0)):
        for k, nome in enumerate(salas):
            sp = mk("IfcSpace", nome, LongName=nome)
            solid(sp, box(0.19 + w * k, 0.19, st.Elevation, w * (k + 1), 7.93, st.Elevation + 2.8))
            agg.assign_object(f, products=[sp], relating_object=st)
            qto(sp, "Qto_SpaceBaseQuantities", {"NetFloorArea": 72.0, "Height": 2.80})
    for nome, area, b in (("Sanitário masculino", 18.0, box(18.0, 0.19, 0, 23.81, 4.0, 2.8)),
                          ("Sanitário feminino", 18.0, box(18.0, 4.1, 0, 23.81, 7.93, 2.8)),
                          ("Circulação", 30.0, box(0.19, 8.07, 0, 23.81, 11.81, 2.8))):
        sp = mk("IfcSpace", nome, LongName=nome)
        solid(sp, b)
        agg.assign_object(f, products=[sp], relating_object=terreo)
        qto(sp, "Qto_SpaceBaseQuantities", {"NetFloorArea": area, "Height": 2.80})

    # ---------------- instalações hidrossanitárias
    af = system.add_system(f, ifc_class="IfcDistributionSystem")
    af.Name, af.PredefinedType = "Água fria", "DOMESTICCOLDWATER"
    es = system.add_system(f, ifc_class="IfcDistributionSystem")
    es.Name, es.PredefinedType = "Esgoto sanitário", "SEWAGE"
    tubos_af = []
    for i, (d, l) in enumerate([(25, 18.0), (25, 12.0), (32, 9.0), (50, 6.0)]):
        p = mk("IfcPipeSegment", f"Tubo PVC soldável DN{d} - trecho {i + 1}", PredefinedType="RIGIDSEGMENT")
        s_ = d / 1000
        y, z = 7.6 - 0.15 * i, 2.6
        solid(p, box(23.7 - l, y, z, 23.7, y + s_, z + s_))
        mat.assign_material(f, products=[p], type="IfcMaterial", material=M["PVC soldável"])
        qto(p, "Qto_PipeSegmentBaseQuantities", {"Length": l})
        ps(p, "Pset_PipeSegmentTypeCommon", {"NominalDiameter": d / 1000})
        tubos_af.append(p)
    tubos_es = []
    for i, (d, l) in enumerate([(100, 14.0), (50, 8.0), (40, 6.0)]):
        p = mk("IfcPipeSegment", f"Tubo PVC esgoto DN{d} - trecho {i + 1}", PredefinedType="RIGIDSEGMENT")
        s_ = d / 1000
        y = 1.0 + 1.2 * i
        solid(p, box(23.9 - l, y, -0.4, 23.9, y + s_, -0.4 + s_))
        mat.assign_material(f, products=[p], type="IfcMaterial", material=M["PVC esgoto série normal"])
        qto(p, "Qto_PipeSegmentBaseQuantities", {"Length": l})
        tubos_es.append(p)
    vasos = [mk("IfcSanitaryTerminal", f"Bacia sanitária com caixa acoplada {i + 1}", PredefinedType="TOILETPAN") for i in range(4)]
    lavs = [mk("IfcSanitaryTerminal", f"Lavatório de louça com coluna {i + 1}", PredefinedType="WASHHANDBASIN") for i in range(4)]
    mics = [mk("IfcSanitaryTerminal", f"Mictório individual {i + 1}", PredefinedType="URINAL") for i in range(2)]
    mat.assign_material(f, products=vasos + lavs + mics, type="IfcMaterial", material=M["Louça sanitária"])
    for i, v in enumerate(vasos):    # junto à fachada leste, 2 por sanitário
        y = (0.6, 2.2, 4.6, 6.2)[i]
        solid(v, box(23.1, y, 0.02, 23.8, y + 0.4, 0.42), box(23.65, y, 0.42, 23.8, y + 0.4, 0.8))
    for i, v in enumerate(lavs):     # bancada junto à divisória T-09
        y = (1.2, 2.6, 4.9, 6.3)[i]
        solid(v, box(20.1, y, 0.75, 20.55, y + 0.4, 0.88))
    for i, v in enumerate(mics):
        x = 18.6 + 0.7 * i
        solid(v, box(x, 0.2, 0.55, x + 0.35, 0.5, 1.15))
    ralos = [mk("IfcWasteTerminal", f"Ralo sifonado DN100 {i + 1}", PredefinedType="FLOORTRAP") for i in range(2)]
    for i, r_ in enumerate(ralos):
        y = 2.0 + 4.0 * i
        solid(r_, box(21.8, y, 0.0, 22.0, y + 0.2, 0.025))
    cx = mk("IfcTank", "Reservatório de água fria 5.000 L", PredefinedType="STORAGE")
    solid(cx, box(19.8, 1.5, 6.8, 21.8, 3.5, 8.5))
    mat.assign_material(f, products=[cx], type="IfcMaterial", material=M["Polietileno"])
    system.assign_system(f, products=tubos_af + lavs + vasos + [cx], system=af)
    system.assign_system(f, products=tubos_es + ralos + mics, system=es)
    put(tubos_af + tubos_es + vasos + lavs + mics + ralos, terreo)
    put([cx], cobertura)

    # ---------------- instalações elétricas
    il = system.add_system(f, ifc_class="IfcDistributionSystem")
    il.Name, il.PredefinedType = "Iluminação e tomadas", "ELECTRICAL"
    lum = [mk("IfcLightFixture", f"Luminária LED de embutir 60x60 cm {i + 1}", PredefinedType="DIRECTIONSOURCE") for i in range(24)]
    tom = [mk("IfcOutlet", f"Tomada 2P+T 10 A {i + 1}", PredefinedType="POWEROUTLET") for i in range(30)]
    qd = mk("IfcElectricDistributionBoard", "Quadro de distribuição QD-B", PredefinedType="DISTRIBUTIONBOARD")
    ele = [mk("IfcCableCarrierSegment", "Eletrocalha perfurada 100x50 mm", PredefinedType="CABLETRAYSEGMENT")]
    for i, lm in enumerate(lum):     # 12 por pavimento, sob o forro
        k, z = i % 12, (2.75 if i < 12 else 6.15)
        x, y = 1.5 + 3.0 * (k % 6), (2.2 if k < 6 else 5.2)
        solid(lm, box(x, y, z, x + 0.6, y + 0.6, z + 0.05))
    for i, tm in enumerate(tom):     # 15 por pavimento, h = 30 cm, nas fachadas e na circulação
        k, z = i % 15, (0.3 if i < 15 else 3.7)
        x, y = (0.8 + 2.4 * k, 0.19) if k < 8 else (1.4 + 3.0 * (k - 8), 7.91)
        solid(tm, box(x, y, z, x + 0.1, y + 0.02, z + 0.1))
    solid(qd, box(22.8, 8.07, 1.2, 23.4, 8.25, 2.1))
    solid(ele[0], box(0.5, 9.9, 2.6, 23.5, 10.0, 2.65))
    qto(ele[0], "Qto_CableCarrierSegmentBaseQuantities", {"Length": 48.0})
    system.assign_system(f, products=lum + tom + [qd] + ele, system=il)
    put(lum[:12] + tom[:15] + [qd] + ele, terreo)
    put(lum[12:] + tom[15:], superior)

    # ---------------- climatização
    ac = system.add_system(f, ifc_class="IfcDistributionSystem")
    ac.Name, ac.PredefinedType = "Ar-condicionado", "AIRCONDITIONING"
    spl = [mk("IfcUnitaryEquipment", f"Condicionador split hi-wall 24.000 BTU/h - {i + 1}", PredefinedType="SPLITSYSTEM") for i in range(6)]
    exa = [mk("IfcFan", f"Exaustor axial para sanitário {i + 1}") for i in range(2)]
    for i, sp_ in enumerate(spl):    # um por sala, na parede da circulação, h = 2,30 m
        x, z = 2.0 + (6.0 if i < 3 else 8.0) * (i % 3), (2.3 if i < 3 else 5.7)
        solid(sp_, box(x, 7.65, z, x + 1.0, 7.93, z + 0.3))
    for i, ex in enumerate(exa):
        y = 1.0 + 4.0 * i
        solid(ex, box(23.5, y, 2.3, 23.81, y + 0.3, 2.6))
    system.assign_system(f, products=spl, system=ac)
    put(spl[:3] + exa, terreo)
    put(spl[3:], superior)

    # ---------------- genéricos (para demonstrar pendências de classificação)
    banc = mk("IfcBuildingElementProxy", "Bancada de granito para lavatórios")
    mat.assign_material(f, products=[banc], type="IfcMaterial", material=M["Granito"])
    solid(banc, box(20.1, 0.8, 0.85, 20.65, 7.0, 0.88))
    sem = solid(mk("IfcBuildingElementProxy", "Elemento sem identificação"), box(16.0, 9.5, 0.0, 16.5, 10.0, 0.5))
    put([banc, sem], terreo)

    out.parent.mkdir(parents=True, exist_ok=True)
    f.write(str(out))
    return out


if __name__ == "__main__":
    p = main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT)
    print("IFC de exemplo gerado em", p)
