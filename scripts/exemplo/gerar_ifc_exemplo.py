"""Gera o IFC do PROJETO EXEMPLO (fictício): Escola SENAI — Bloco B de salas de aula.

Dados inventados para DEMONSTRAÇÃO do BIMOFFICE Knowledge — não representam obra real.
Contém, de propósito, algumas lacunas (vigas sem volume, bancada genérica sem classificação,
parede de drywall sem quantitativos) para demonstrar a detecção de pendências.

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

    def wall(name, storey, lset, length, external, x=0.0, y=0.0, with_qto=True, fire=None):
        thick = sum(l.LayerThickness for l in lset.MaterialLayers)
        h = 3.40
        w = mk("IfcWall", name)
        rep = geo.add_wall_representation(f, context=body, length=length, height=h, thickness=thick)
        geo.assign_representation(f, product=w, representation=rep)
        m = np.eye(4)
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
        wall(f"Parede externa {tag}-01 (fachada norte)", st, ext, 24.0, True, 0, 0, fire="EI 60")
        wall(f"Parede externa {tag}-02 (fachada leste)", st, ext, 12.0, True, 24, 0, fire="EI 60")
        wall(f"Parede externa {tag}-03 (fachada sul)", st, ext, 24.0, True, 0, 12, fire="EI 60")
        wall(f"Parede externa {tag}-04 (fachada oeste)", st, ext, 12.0, True, 0, 0, fire="EI 60")
        for i in range(3):
            wall(f"Parede interna {tag}-{i + 5:02d}", st, inn, 8.0, False, 6.0 * (i + 1), 0)
    wall("Divisória sanitários T-08", terreo, dry, 4.0, False, 20, 4)
    wall("Divisória sanitários T-09 (sem quantitativos no IFC)", terreo, dry, 4.0, False, 22, 4, with_qto=False)

    # ---------------- estrutura de concreto
    for i in range(8):
        s = mk("IfcFooting", f"Sapata S{i + 1}", PredefinedType="PAD_FOOTING")
        mat.assign_material(f, products=[s], type="IfcMaterial", material=M["Concreto C30"])
        qto(s, "Qto_FootingBaseQuantities", {"Length": 1.6, "Width": 1.6, "Height": 0.5, "NetVolume": 1.28})
        put([s], terreo)
    for st in (terreo, superior):
        for i in range(8):
            c = mk("IfcColumn", f"Pilar P{i + 1} ({st.Name})")
            mat.assign_material(f, products=[c], type="IfcMaterial", material=M["Concreto C30"])
            qto(c, "Qto_ColumnBaseQuantities", {"Length": 3.4, "CrossSectionArea": 0.09, "NetVolume": 0.306})
            ps(c, "Pset_ColumnCommon", {"LoadBearing": True})
            put([c], st)
        for i in range(6):  # vigas SEM volume no IFC (lacuna proposital)
            b = mk("IfcBeam", f"Viga V{i + 1} 20x50 ({st.Name})")
            mat.assign_material(f, products=[b], type="IfcMaterial", material=M["Concreto C30"])
            ps(b, "Pset_BeamCommon", {"LoadBearing": True})
            put([b], st)
    for st, nome, area in ((superior, "Laje do Pavimento Superior", 288.0), (cobertura, "Laje de forro da cobertura", 288.0)):
        lj = mk("IfcSlab", nome, PredefinedType="FLOOR")
        mat.assign_material(f, products=[lj], type="IfcMaterial", material=M["Concreto C30"])
        ps(lj, "Pset_SlabCommon", {"LoadBearing": True, "IsExternal": False})
        qto(lj, "Qto_SlabBaseQuantities", {"Width": 0.12, "GrossArea": area, "NetArea": area, "NetVolume": area * 0.12})
        put([lj], st)
    esc = mk("IfcStair", "Escada de concreto armado (2 lances)", PredefinedType="HALF_TURN_STAIR")
    mat.assign_material(f, products=[esc], type="IfcMaterial", material=M["Concreto C30"])
    gc = mk("IfcRailing", "Guarda-corpo metálico h=1,10 m", PredefinedType="GUARDRAIL")
    mat.assign_material(f, products=[gc], type="IfcMaterial", material=M["Aço ASTM A36"])
    qto(gc, "Qto_RailingBaseQuantities", {"Length": 9.6})
    put([esc, gc], terreo)

    # ---------------- cobertura metálica
    for i in range(6):
        t = mk("IfcBeam", f"Tesoura metálica TS{i + 1}")
        mat.assign_material(f, products=[t], type="IfcMaterial", material=M["Aço ASTM A572 Gr.50"])
        put([t], cobertura)
    for i in range(10):
        t = mk("IfcMember", f"Terça metálica perfil U 150x60 - T{i + 1}", PredefinedType="PURLIN")
        mat.assign_material(f, products=[t], type="IfcMaterial", material=M["Aço ASTM A36"])
        qto(t, "Qto_MemberBaseQuantities", {"Length": 12.0})
        put([t], cobertura)
    telhado = mk("IfcRoof", "Cobertura em duas águas", PredefinedType="GABLE_ROOF")
    telha = mk("IfcCovering", "Telha termoacústica trapezoidal (sanduíche 30 mm)", PredefinedType="ROOFING")
    mat.assign_material(f, products=[telha], type="IfcMaterial", material=M["Telha termoacústica aço galvanizado + PIR 30 mm"])
    qto(telha, "Qto_CoveringBaseQuantities", {"Width": 0.03, "NetArea": 320.0})
    ps(telha, "Pset_CoveringCommon", {"IsExternal": True})
    put([telhado, telha], cobertura)

    # ---------------- acabamentos
    def cov(name, ptype, material, area, storey, extra=None):
        c = mk("IfcCovering", name, PredefinedType=ptype)
        mat.assign_material(f, products=[c], type="IfcMaterial", material=M[material])
        q = {"NetArea": area}
        if extra:
            q.update(extra)
        qto(c, "Qto_CoveringBaseQuantities", q)
        put([c], storey)
    cov("Piso porcelanato - salas do térreo", "FLOORING", "Porcelanato 60x60 cm", 216.0, terreo)
    cov("Piso porcelanato - salas do superior", "FLOORING", "Porcelanato 60x60 cm", 216.0, superior)
    cov("Piso antiderrapante - sanitários", "FLOORING", "Piso cerâmico antiderrapante 45x45 cm", 36.0, terreo)
    cov("Revestimento de parede - sanitários (até o teto)", "CLADDING", "Revestimento cerâmico 30x60 cm", 92.0, terreo)
    cov("Forro de gesso acartonado - térreo", "CEILING", "Gesso acartonado (forro)", 252.0, terreo)
    cov("Forro de gesso acartonado - superior", "CEILING", "Gesso acartonado (forro)", 252.0, superior)

    # ---------------- esquadrias (tipos)
    def door_type(name, w, h, material):
        t = mk("IfcDoorType", name, PredefinedType="DOOR", OperationType="SINGLE_SWING_LEFT")
        mat.assign_material(f, products=[t], type="IfcMaterial", material=M[material])
        return t, w, h

    def add_doors(dt, n, storey, prefix):
        t, w, h = dt
        objs = [mk("IfcDoor", f"{prefix}{i + 1}", OverallWidth=w, OverallHeight=h) for i in range(n)]
        typ.assign_type(f, related_objects=objs, relating_type=t)
        put(objs, storey)

    pm = door_type("Porta de madeira semi-oca 90x210 cm", 0.9, 2.1, "Madeira (porta semi-oca)")
    pa = door_type("Porta de alumínio veneziana 80x210 cm", 0.8, 2.1, "Alumínio anodizado")
    pp = door_type("Porta acessível 90x210 cm com barra horizontal", 0.9, 2.1, "Madeira (porta semi-oca)")
    add_doors(pm, 3, terreo, "PM-T")
    add_doors(pm, 3, superior, "PM-S")
    add_doors(pa, 2, terreo, "PA-T")
    add_doors(pp, 2, terreo, "PNE-T")
    jt = mk("IfcWindowType", "Janela de alumínio de correr 200x120 cm, 2 folhas", PredefinedType="WINDOW",
            PartitioningType="DOUBLE_PANEL_VERTICAL")
    ws = mat.add_material_set(f, name="Alumínio + vidro", set_type="IfcMaterialConstituentSet")
    mat.add_constituent(f, constituent_set=ws, material=M["Alumínio anodizado"]).Name = "Caixilho"
    mat.add_constituent(f, constituent_set=ws, material=M["Vidro temperado 6 mm"]).Name = "Vidro"
    mat.assign_material(f, products=[jt], type="IfcMaterialConstituentSet", material=ws)
    for st, tag in ((terreo, "T"), (superior, "S")):
        js = [mk("IfcWindow", f"J{tag}{i + 1}", OverallWidth=2.0, OverallHeight=1.2) for i in range(6)]
        typ.assign_type(f, related_objects=js, relating_type=jt)
        put(js, st)

    # ---------------- ambientes
    for st, salas in ((terreo, ["Sala de aula 01", "Sala de aula 02", "Sala de aula 03"]),
                      (superior, ["Sala de aula 04", "Sala de aula 05", "Laboratório de informática"])):
        for nome in salas:
            sp = mk("IfcSpace", nome, LongName=nome)
            agg.assign_object(f, products=[sp], relating_object=st)
            qto(sp, "Qto_SpaceBaseQuantities", {"NetFloorArea": 72.0, "Height": 2.80})
    for nome, area in (("Sanitário masculino", 18.0), ("Sanitário feminino", 18.0), ("Circulação", 30.0)):
        sp = mk("IfcSpace", nome, LongName=nome)
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
        mat.assign_material(f, products=[p], type="IfcMaterial", material=M["PVC soldável"])
        qto(p, "Qto_PipeSegmentBaseQuantities", {"Length": l})
        ps(p, "Pset_PipeSegmentTypeCommon", {"NominalDiameter": d / 1000})
        tubos_af.append(p)
    tubos_es = []
    for i, (d, l) in enumerate([(100, 14.0), (50, 8.0), (40, 6.0)]):
        p = mk("IfcPipeSegment", f"Tubo PVC esgoto DN{d} - trecho {i + 1}", PredefinedType="RIGIDSEGMENT")
        mat.assign_material(f, products=[p], type="IfcMaterial", material=M["PVC esgoto série normal"])
        qto(p, "Qto_PipeSegmentBaseQuantities", {"Length": l})
        tubos_es.append(p)
    vasos = [mk("IfcSanitaryTerminal", f"Bacia sanitária com caixa acoplada {i + 1}", PredefinedType="TOILETPAN") for i in range(4)]
    lavs = [mk("IfcSanitaryTerminal", f"Lavatório de louça com coluna {i + 1}", PredefinedType="WASHHANDBASIN") for i in range(4)]
    mics = [mk("IfcSanitaryTerminal", f"Mictório individual {i + 1}", PredefinedType="URINAL") for i in range(2)]
    mat.assign_material(f, products=vasos + lavs + mics, type="IfcMaterial", material=M["Louça sanitária"])
    ralos = [mk("IfcWasteTerminal", f"Ralo sifonado DN100 {i + 1}", PredefinedType="FLOORTRAP") for i in range(2)]
    cx = mk("IfcTank", "Reservatório de água fria 5.000 L", PredefinedType="STORAGE")
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
    qto(ele[0], "Qto_CableCarrierSegmentBaseQuantities", {"Length": 48.0})
    system.assign_system(f, products=lum + tom + [qd] + ele, system=il)
    put(lum[:12] + tom[:15] + [qd] + ele, terreo)
    put(lum[12:] + tom[15:], superior)

    # ---------------- climatização
    ac = system.add_system(f, ifc_class="IfcDistributionSystem")
    ac.Name, ac.PredefinedType = "Ar-condicionado", "AIRCONDITIONING"
    spl = [mk("IfcUnitaryEquipment", f"Condicionador split hi-wall 24.000 BTU/h - {i + 1}", PredefinedType="SPLITSYSTEM") for i in range(6)]
    exa = [mk("IfcFan", f"Exaustor axial para sanitário {i + 1}") for i in range(2)]
    system.assign_system(f, products=spl, system=ac)
    put(spl[:3] + exa, terreo)
    put(spl[3:], superior)

    # ---------------- genéricos (para demonstrar pendências de classificação)
    banc = mk("IfcBuildingElementProxy", "Bancada de granito para lavatórios")
    mat.assign_material(f, products=[banc], type="IfcMaterial", material=M["Granito"])
    put([banc, mk("IfcBuildingElementProxy", "Elemento sem identificação")], terreo)

    out.parent.mkdir(parents=True, exist_ok=True)
    f.write(str(out))
    return out


if __name__ == "__main__":
    p = main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT)
    print("IFC de exemplo gerado em", p)
