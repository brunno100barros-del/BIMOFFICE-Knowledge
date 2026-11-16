"""Classificação de elementos IFC por disciplina — regras explicáveis.

Ordem das evidências (da mais forte para a mais fraca):
1. Classe IFC específica (ex.: IfcPipeSegment, IfcBeam, IfcDoor)          -> confiança alta
2. Tipo associado (IFC2X3: IfcFlowSegment + IfcPipeSegmentType)             -> alta
3. Sistema ao qual pertence (IfcDistributionSystem.PredefinedType)          -> alta
4. Propriedades (Pset_*Common.LoadBearing) e material (aço -> metálica)     -> alta/média
5. Nome do sistema                                                          -> média
6. Nome do elemento -> NUNCA classifica sozinho: vira só uma SUGESTÃO
   ("Pendente", com sugestão inferida de baixa confiança).

Toda decisão guarda os motivos (`reasons`) para o usuário conferir.
"""
from __future__ import annotations

import re

ARQ, EST, MET, HID, ELE, CLI, INST, OUT, PEND = (
    "Arquitetura", "Estrutura", "Estrutura metálica", "Hidrossanitário",
    "Elétrica", "Climatização", "Instalações (indefinida)", "Outros", "Pendente",
)
DISCIPLINES = [ARQ, EST, MET, HID, ELE, CLI, INST, OUT, PEND]

# classe IFC -> disciplina (IFC4/IFC4X3; várias também existem no IFC2X3)
CLASS_RULES: dict[str, str] = {}
for cls in ("IfcDoor IfcWindow IfcCovering IfcCurtainWall IfcRailing IfcStair IfcStairFlight "
            "IfcRamp IfcRampFlight IfcRoof IfcFurnishingElement IfcFurniture IfcSpace "
            "IfcShadingDevice IfcSystemFurnitureElement").split():
    CLASS_RULES[cls] = ARQ
for cls in ("IfcBeam IfcBeamStandardCase IfcColumn IfcColumnStandardCase IfcFooting IfcPile "
            "IfcMember IfcMemberStandardCase IfcReinforcingBar IfcReinforcingMesh IfcTendon "
            "IfcTendonAnchor IfcReinforcingElement IfcStructuralMember").split():
    CLASS_RULES[cls] = EST
for cls in ("IfcPipeSegment IfcPipeFitting IfcSanitaryTerminal IfcWasteTerminal IfcValve IfcPump "
            "IfcTank IfcInterceptor IfcFireSuppressionTerminal IfcStackTerminal").split():
    CLASS_RULES[cls] = HID
for cls in ("IfcCableSegment IfcCableFitting IfcCableCarrierSegment IfcCableCarrierFitting "
            "IfcLightFixture IfcLamp IfcOutlet IfcSwitchingDevice IfcElectricDistributionBoard "
            "IfcProtectiveDevice IfcJunctionBox IfcElectricAppliance IfcElectricMotor "
            "IfcElectricGenerator IfcTransformer IfcCommunicationsAppliance IfcAudioVisualAppliance "
            "IfcAlarm IfcSensor IfcElectricFlowStorageDevice IfcSolarDevice").split():
    CLASS_RULES[cls] = ELE
for cls in ("IfcDuctSegment IfcDuctFitting IfcDuctSilencer IfcAirTerminal IfcAirTerminalBox "
            "IfcAirToAirHeatRecovery IfcFan IfcChiller IfcCoil IfcCompressor IfcCondenser "
            "IfcCoolingTower IfcDamper IfcEvaporativeCooler IfcEvaporator IfcFilter IfcHeatExchanger "
            "IfcHumidifier IfcUnitaryEquipment IfcBoiler IfcSpaceHeater IfcBurner").split():
    CLASS_RULES[cls] = CLI

# IFC2X3: classes genéricas de fluxo -> decide pelo TIPO associado
TYPE_RULES = {}
for t, d in CLASS_RULES.items():
    TYPE_RULES[t + "Type"] = d
TYPE_RULES.update({"IfcElectricDistributionPointType": ELE, "IfcLightFixtureType": ELE,
                   "IfcGasTerminalType": HID, "IfcFlowMeterType": INST})

GENERIC_MEP = {"IfcFlowSegment", "IfcFlowFitting", "IfcFlowTerminal", "IfcFlowController",
               "IfcFlowMovingDevice", "IfcFlowStorageDevice", "IfcFlowTreatmentDevice",
               "IfcEnergyConversionDevice", "IfcDistributionFlowElement", "IfcDistributionElement",
               "IfcDistributionControlElement"}

# IfcDistributionSystem.PredefinedType (IFC4) -> disciplina
SYSTEM_PREDEFINED = {
    **{k: HID for k in ("DOMESTICCOLDWATER", "DOMESTICHOTWATER", "DRAINAGE", "SEWAGE", "STORMWATER",
                        "WASTEWATER", "RAINWATER", "WATERSUPPLY", "FIREPROTECTION", "SPRINKLER",
                        "GAS", "FUEL", "WATER")},
    **{k: ELE for k in ("ELECTRICAL", "LIGHTING", "POWERGENERATION", "EARTHING", "LIGHTNINGPROTECTION",
                        "COMMUNICATION", "DATA", "SECURITY", "SIGNAL", "TELEPHONE", "TV", "CONTROL",
                        "ELECTROACOUSTIC", "FIREALARM")},
    **{k: CLI for k in ("AIRCONDITIONING", "VENTILATION", "EXHAUST", "HEATING", "CHILLEDWATER",
                        "CONDENSERWATER", "REFRIGERATION", "COOLING")},
}
# palavras no NOME DO SISTEMA (evidência média) e no NOME DO ELEMENTO (só sugestão)
KEYWORDS = [
    (HID, r"\b(água|agua|esgoto|pluvial|hidr|sanit|ralo|lavat|vaso|bacia|registro|torneira|chuveiro|"
          r"tubo|tubula|caixa sifonada|reservat|incêndio|incendio|hidrante|sprinkler|gás|gas)\w*"),
    (ELE, r"\b(elétr|eletr|ilumina|lumin|lâmpada|lampada|tomada|interruptor|quadro|disjunt|cabo|"
          r"eletroduto|eletrocalha|spda|aterramento|logic|dados|cftv|alarme)\w*"),
    (CLI, r"\b(ar condicionado|ar-condicionado|climatiza|ventila|exaust|duto|insufla|retorno|"
          r"splitão|split|fan ?coil|chiller|difusor|grelha|hvac)\w*"),
    (EST, r"\b(pilar|viga|sapata|estaca|bloco de coroamento|baldrame|laje|funda[çc])\w*"),
]
STEEL = re.compile(r"\b(aço|aco|steel|metál|metal|astm a|ar-?350|s235|s275|s355)", re.IGNORECASE)
AUXILIARY = {"IfcOpeningElement", "IfcOpeningStandardCase", "IfcVirtualElement", "IfcAnnotation",
             "IfcGrid", "IfcSpatialZone", "IfcVoidingFeature", "IfcSurfaceFeature"}


def _kw(text: str) -> str | None:
    t = (text or "").lower()
    for disc, rx in KEYWORDS:
        if re.search(rx, t):
            return disc
    return None


def classify(info: dict) -> dict:
    """`info`: ifc_class, type_class, systems[{name, predefined}], materials[{name, category}],
    psets{...}, name. Retorna {discipline, confidence, reasons, suggestion}."""
    cls = info.get("ifc_class", "")
    reasons: list[str] = []
    mats = info.get("materials") or []
    mat_text = " ".join(f"{m.get('name') or ''} {m.get('category') or ''}" for m in mats)
    is_steel = bool(STEEL.search(mat_text))
    load_bearing = None
    for pname, props in (info.get("psets") or {}).items():
        if pname.endswith("Common") and isinstance(props, dict) and "LoadBearing" in props:
            load_bearing = props["LoadBearing"]
            break

    def result(disc, conf, suggestion=None):
        return {"discipline": disc, "confidence": conf, "reasons": reasons, "suggestion": suggestion}

    # 1) classe específica
    if cls in CLASS_RULES:
        disc = CLASS_RULES[cls]
        reasons.append(f"classe IFC {cls}")
        if disc == EST and is_steel:
            reasons.append("material metálico")
            return result(MET, "alta")
        return result(disc, "alta")

    # paredes, lajes e placas: depende de LoadBearing / material
    if cls in ("IfcWall", "IfcWallStandardCase", "IfcWallElementedCase", "IfcSlab",
               "IfcSlabStandardCase", "IfcPlate", "IfcPlateStandardCase", "IfcChimney"):
        if load_bearing is True:
            reasons += [f"classe IFC {cls}", "propriedade LoadBearing = verdadeiro"]
            return result(MET if is_steel else EST, "alta")
        if load_bearing is False:
            reasons += [f"classe IFC {cls}", "propriedade LoadBearing = falso"]
            return result(ARQ, "alta")
        if cls.startswith("IfcSlab"):
            reasons += [f"classe IFC {cls}", "sem LoadBearing: lajes costumam ser estruturais — conferir"]
            return result(EST, "média")
        if cls.startswith("IfcPlate") and is_steel:
            reasons += [f"classe IFC {cls}", "material metálico"]
            return result(MET, "média")
        reasons += [f"classe IFC {cls}", "sem informação de LoadBearing — conferir"]
        return result(ARQ, "média")

    # 2) IFC2X3 e genéricos de fluxo: tipo associado
    tcls = info.get("type_class")
    if tcls and tcls in TYPE_RULES:
        reasons.append(f"tipo associado {tcls}")
        return result(TYPE_RULES[tcls], "alta")

    # 3) sistema
    for s in info.get("systems") or []:
        pre = (s.get("predefined") or "").upper()
        if pre in SYSTEM_PREDEFINED:
            reasons.append(f"sistema «{s.get('name')}» do tipo {pre}")
            return result(SYSTEM_PREDEFINED[pre], "alta")
    for s in info.get("systems") or []:
        d = _kw(s.get("name") or "")
        if d and d != EST:
            reasons.append(f"nome do sistema «{s.get('name')}»")
            return result(d, "média")

    if cls in GENERIC_MEP:
        reasons.append(f"classe genérica de instalações {cls} sem tipo/sistema identificável")
        return result(INST, "média", _suggest(info))
    if cls in ("IfcFooting",):
        reasons.append(f"classe IFC {cls}")
        return result(EST, "alta")
    if cls in ("IfcDiscreteAccessory", "IfcFastener", "IfcMechanicalFastener", "IfcBuildingElementPart",
               "IfcElementAssembly", "IfcGeographicElement", "IfcCivilElement", "IfcEarthworksFill",
               "IfcEarthworksCut", "IfcTransportElement"):
        reasons.append(f"classe IFC {cls} (não específica de uma disciplina)")
        return result(OUT, "média")

    # 6) genérico (proxy etc.): nome NÃO classifica sozinho
    reasons.append(f"classe genérica {cls}: sem evidência técnica suficiente")
    return result(PEND, "baixa", _suggest(info))


def _suggest(info: dict) -> dict | None:
    d = _kw(info.get("name") or "") or _kw(info.get("type_name") or "")
    if d:
        return {"discipline": d, "confidence": "baixa",
                "reason": "inferido apenas pelo nome — confirme antes de usar"}
    return None
