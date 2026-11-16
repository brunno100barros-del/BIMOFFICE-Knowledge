"""Gera modelos IFC de TESTE (IFC2X3 ou IFC4) com conteúdo CONHECIDO.

Dados fictícios usados só para conferir o leitor: cada valor aqui é o "gabarito" dos testes.
"""
from __future__ import annotations

from pathlib import Path

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.classification
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.material
import ifcopenshell.api.owner
import ifcopenshell.api.owner.settings
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.system
import ifcopenshell.api.type
import ifcopenshell.api.unit
import numpy as np


def _mk(f, cls, name=None, **attrs):
    e = ifcopenshell.api.root.create_entity(f, ifc_class=cls, name=name)
    for k, v in attrs.items():
        setattr(e, k, v)
    return e


def build_model(path: Path, schema: str = "IFC4", n_extra_walls: int = 0) -> Path:
    is2x3 = schema.upper() == "IFC2X3"
    f = ifcopenshell.api.project.create_file(version=schema.upper())
    # IFC2X3 exige histórico de autoria (OwnerHistory) em cada objeto
    person = f.createIfcPerson(FamilyName="Teste")
    org = f.createIfcOrganization(Name="BIMOFFICE testes")
    user = f.createIfcPersonAndOrganization(person, org)
    app = f.createIfcApplication(org, "1.0", "BIMOFFICE gerador de testes", "bimoffice-tests")
    old = (ifcopenshell.api.owner.settings.get_user, ifcopenshell.api.owner.settings.get_application)
    ifcopenshell.api.owner.settings.get_user = lambda _f: user
    ifcopenshell.api.owner.settings.get_application = lambda _f: app
    try:
        return _build(f, path, is2x3, n_extra_walls)
    finally:
        ifcopenshell.api.owner.settings.get_user, ifcopenshell.api.owner.settings.get_application = old


def _build(f, path: Path, is2x3: bool, n_extra_walls: int) -> Path:
    project = _mk(f, "IfcProject", "Projeto Teste BIMOFFICE")
    ifcopenshell.api.unit.assign_unit(  # metros, m², m³ (SI)
        f, length={"is_metric": True, "raw": "METERS"},
        area={"is_metric": True, "raw": "SQUARE_METERS"},
        volume={"is_metric": True, "raw": "CUBIC_METERS"})
    model = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model)

    site = _mk(f, "IfcSite", "Terreno")
    building = _mk(f, "IfcBuilding", "Bloco de Salas")
    terreo = _mk(f, "IfcBuildingStorey", "Térreo", Elevation=0.0)
    pav1 = _mk(f, "IfcBuildingStorey", "Pavimento 1", Elevation=3.0)
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(f, products=[building], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(f, products=[terreo, pav1], relating_object=building)

    def put(elems, storey):
        ifcopenshell.api.spatial.assign_container(f, products=elems, relating_structure=storey)

    # --- materiais (IFC2X3 não tem "Category" no material)
    def add_mat(name, cat):
        return ifcopenshell.api.material.add_material(f, name=name, category=None if is2x3 else cat)

    bloco = add_mat("Bloco cerâmico", "block")
    reboco = add_mat("Argamassa de reboco", "plaster")
    concreto = add_mat("Concreto C30", "concrete")
    aco = add_mat("Aço ASTM A572", "steel")
    pvc = add_mat("PVC", "plastic")
    lset = ifcopenshell.api.material.add_material_set(f, name="Alvenaria 14 cm", set_type="IfcMaterialLayerSet")
    l1 = ifcopenshell.api.material.add_layer(f, layer_set=lset, material=reboco)
    l1.LayerThickness = 0.02
    l2 = ifcopenshell.api.material.add_layer(f, layer_set=lset, material=bloco)
    l2.LayerThickness = 0.10
    l3 = ifcopenshell.api.material.add_layer(f, layer_set=lset, material=reboco)
    l3.LayerThickness = 0.02

    wall_cls = "IfcWallStandardCase" if is2x3 else "IfcWall"
    # --- paredes (com geometria real 5 x 3 x 0,14 m)
    walls = []
    for i in range(2 + n_extra_walls):
        w = _mk(f, wall_cls, f"Parede externa {i + 1}")
        rep = ifcopenshell.api.geometry.add_wall_representation(f, context=body, length=5.0, height=3.0, thickness=0.14)
        ifcopenshell.api.geometry.assign_representation(f, product=w, representation=rep)
        m = np.eye(4)
        m[0, 3] = i * 6.0
        ifcopenshell.api.geometry.edit_object_placement(f, product=w, matrix=m)
        ifcopenshell.api.material.assign_material(f, products=[w], type="IfcMaterialLayerSetUsage", material=lset)
        ps = ifcopenshell.api.pset.add_pset(f, product=w, name="Pset_WallCommon")
        ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={"IsExternal": True, "LoadBearing": False, "FireRating": "EI 60"})
        q = ifcopenshell.api.pset.add_qto(f, product=w, name="Qto_WallBaseQuantities")
        ifcopenshell.api.pset.edit_qto(f, qto=q, properties={"Length": 5.0, "Height": 3.0, "Width": 0.14, "NetSideArea": 15.0, "NetVolume": 2.1})
        walls.append(w)
    put(walls, terreo)
    # parede SEM quantidades declaradas (só geometria) -> testa cálculo geométrico
    wg = _mk(f, wall_cls, "Parede interna sem quantitativos")
    rep = ifcopenshell.api.geometry.add_wall_representation(f, context=body, length=4.0, height=3.0, thickness=0.14)
    ifcopenshell.api.geometry.assign_representation(f, product=wg, representation=rep)
    put([wg], terreo)
    # parede estrutural (LoadBearing) de concreto
    wc = _mk(f, wall_cls, "Parede de contenção")
    ifcopenshell.api.material.assign_material(f, products=[wc], type="IfcMaterial", material=concreto)
    ps = ifcopenshell.api.pset.add_pset(f, product=wc, name="Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={"LoadBearing": True})
    put([wc], terreo)

    # --- laje
    slab = _mk(f, "IfcSlab", "Laje L1", PredefinedType="FLOOR")
    ifcopenshell.api.material.assign_material(f, products=[slab], type="IfcMaterial", material=concreto)
    ps = ifcopenshell.api.pset.add_pset(f, product=slab, name="Pset_SlabCommon")
    ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={"LoadBearing": True, "IsExternal": False})
    q = ifcopenshell.api.pset.add_qto(f, product=slab, name="Qto_SlabBaseQuantities")
    ifcopenshell.api.pset.edit_qto(f, qto=q, properties={"Width": 0.12, "GrossArea": 50.0, "NetVolume": 6.0})
    put([slab], pav1)

    # --- pilares e vigas
    pc = _mk(f, "IfcColumn", "P1 - pilar de concreto")
    ifcopenshell.api.material.assign_material(f, products=[pc], type="IfcMaterial", material=concreto)
    pm = _mk(f, "IfcColumn", "P2 - pilar metálico")
    ifcopenshell.api.material.assign_material(f, products=[pm], type="IfcMaterial", material=aco)
    vm = _mk(f, "IfcBeam", "V1 - viga metálica")
    ifcopenshell.api.material.assign_material(f, products=[vm], type="IfcMaterial", material=aco)
    sap = _mk(f, "IfcFooting", "Sapata S1")
    ifcopenshell.api.material.assign_material(f, products=[sap], type="IfcMaterial", material=concreto)
    put([pc, pm, vm, sap], terreo)

    # --- portas e janelas (dimensões nos atributos)
    porta = _mk(f, "IfcDoor", "Porta P1", OverallHeight=2.1, OverallWidth=0.8)
    janela = _mk(f, "IfcWindow", "Janela J1", OverallHeight=1.2, OverallWidth=1.5)
    put([porta, janela], terreo)

    # --- ambiente
    sala = _mk(f, "IfcSpace", "Sanitário masculino", LongName="WC Masc.")
    ifcopenshell.api.aggregate.assign_object(f, products=[sala], relating_object=terreo)
    q = ifcopenshell.api.pset.add_qto(f, product=sala, name="Qto_SpaceBaseQuantities")
    ifcopenshell.api.pset.edit_qto(f, qto=q, properties={"NetFloorArea": 12.5})

    # --- instalações (classes diferem entre IFC2X3 e IFC4)
    if is2x3:
        tubo = _mk(f, "IfcFlowSegment", "Tubo AF 25 mm")
        tt = _mk(f, "IfcPipeSegmentType", "Tubo PVC soldável 25", PredefinedType="RIGIDSEGMENT")
        ifcopenshell.api.type.assign_type(f, related_objects=[tubo], relating_type=tt)
        lav = _mk(f, "IfcFlowTerminal", "Lavatório")
        lt = _mk(f, "IfcSanitaryTerminalType", "Lavatório de louça", PredefinedType="WASHHANDBASIN")
        ifcopenshell.api.type.assign_type(f, related_objects=[lav], relating_type=lt)
        lum = _mk(f, "IfcFlowTerminal", "Luminária LED")
        lft = _mk(f, "IfcLightFixtureType", "Luminária de embutir", PredefinedType="DIRECTIONSOURCE")
        ifcopenshell.api.type.assign_type(f, related_objects=[lum], relating_type=lft)
        duto = _mk(f, "IfcFlowSegment", "Duto de insuflamento")
        dt = _mk(f, "IfcDuctSegmentType", "Duto retangular", PredefinedType="RIGIDSEGMENT")
        ifcopenshell.api.type.assign_type(f, related_objects=[duto], relating_type=dt)
        sistema = ifcopenshell.api.system.add_system(f, ifc_class="IfcSystem")
        sistema.Name = "Água fria"
    else:
        tubo = _mk(f, "IfcPipeSegment", "Tubo AF 25 mm")
        lav = _mk(f, "IfcSanitaryTerminal", "Lavatório", PredefinedType="WASHHANDBASIN")
        lum = _mk(f, "IfcLightFixture", "Luminária LED")
        duto = _mk(f, "IfcDuctSegment", "Duto de insuflamento")
        sistema = ifcopenshell.api.system.add_system(f, ifc_class="IfcDistributionSystem")
        sistema.Name = "Água fria"
        sistema.PredefinedType = "DOMESTICCOLDWATER"
    ifcopenshell.api.material.assign_material(f, products=[tubo], type="IfcMaterial", material=pvc)
    ifcopenshell.api.system.assign_system(f, products=[tubo, lav], system=sistema)
    put([tubo, lav, lum, duto], terreo)

    # --- elemento genérico sem nada (deve ficar "pendente")
    proxy = _mk(f, "IfcBuildingElementProxy", "Elemento 123")
    put([proxy], terreo)
    # elemento genérico cujo NOME sugere disciplina (não deve ser classificado só pelo nome com confiança alta)
    proxy2 = _mk(f, "IfcBuildingElementProxy", "Ralo sifonado")
    put([proxy2], terreo)

    # --- classificação
    sinapi = ifcopenshell.api.classification.add_classification(f, classification="Uniclass")
    ifcopenshell.api.classification.add_reference(
        f, products=[walls[0]], identification="Ss_25_10_30", name="Masonry wall systems", classification=sinapi)

    f.write(str(path))
    return path
