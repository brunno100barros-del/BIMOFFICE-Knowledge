"""Geração dos capítulos do memorial a partir do inventário IFC — SEM IA, só fatos.

Regras (CLAUDE.md):
- Cada frase usa SOMENTE dados que existem no IFC (nomes, materiais, quantidades, propriedades).
- Cada número registra a origem (`facts`): arquivo, método (explícito / atributo / geométrico).
- Falta de informação vira PENDÊNCIA, nunca valor inventado.
- Textos de memoriais de referência NÃO entram aqui: viram sugestões (inseridas só pelo usuário).
"""
from __future__ import annotations

import re
from collections import defaultdict

PT_TYPES = {  # PredefinedType -> nome em português (só tradução do código do IFC)
    "TOILETPAN": "bacias sanitárias", "WASHHANDBASIN": "lavatórios", "URINAL": "mictórios", "SINK": "pias",
    "SHOWER": "chuveiros", "BATH": "banheiras", "FLOORTRAP": "ralos", "STORAGE": "reservatórios",
    "PAD_FOOTING": "sapatas isoladas", "STRIP_FOOTING": "sapatas corridas", "PILE_CAP": "blocos de coroamento",
    "FOOTING_BEAM": "vigas baldrame", "PURLIN": "terças", "FLOOR": "piso", "ROOF": "cobertura",
    "GUARDRAIL": "guarda-corpo", "HANDRAIL": "corrimão",
}
METHOD_PT = {"explicito": "quantidade explícita no IFC", "atributo": "atributo do elemento no IFC",
             "geometrico": "calculado pela geometria 3D do IFC (aproximação)"}


def num(v: float, d: int = 2) -> str:
    s = f"{v:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def cm(v_m: float) -> str:
    """0,0125 m -> '1,25'; 0,14 m -> '14' (sem zeros desnecessários e sem arredondar demais)."""
    t = num(v_m * 100, 2)
    return t.rstrip("0").rstrip(",") if "," in t else t


def base_name(name: str | None) -> str:
    """'Tomada 2P+T 10 A 12' -> 'Tomada 2P+T 10 A' (agrupa itens numerados do mesmo tipo)."""
    n = (name or "(sem nome)").strip()
    n = re.sub(r"\s*\((?:térreo|pavimento[^)]*|cobertura)\)\s*$", "", n, flags=re.I)
    n = re.sub(r"[\s\-–—]*(?:[A-Z]{1,3}-?)?\d+[A-Z]?$", "", n).strip(" -–—")
    n = re.sub(r"[\s\-–—]+(?:trecho|item|unidade|peça|peca)$", "", n, flags=re.I).strip(" -–—")
    return n or (name or "(sem nome)")


class Ctx:
    """Contexto de geração: elementos do modelo + rótulo de origem."""

    def __init__(self, elements: list[dict], source_label: str, storey_order: list[str] | None = None):
        self.els = elements
        self.src = source_label
        self.storey_rank = {n: i for i, n in enumerate(storey_order or [])}
        self.used: dict[str, None] = {}  # GlobalIds dos elementos usados pelo capítulo em construção

    def where(self, pred) -> list[dict]:
        out = [e for e in self.els if pred(e)]
        for e in out:
            if e.get("global_id"):
                self.used[e["global_id"]] = None
        return out


def q_first(e: dict, names, methods=("explicito", "atributo", "geometrico")) -> dict | None:
    for m in methods:
        for q in e.get("quantities") or []:
            if q["name"] in names and q["method"] == m and isinstance(q.get("value"), (int, float)):
                return q
    return None


def q_sum(els: list[dict], names) -> tuple[float, int, set]:
    """Soma a 1ª quantidade encontrada de cada elemento. Retorna (total, nº elementos com valor, métodos)."""
    total, n, methods = 0.0, 0, set()
    for e in els:
        q = q_first(e, names)
        if q:
            total += q["value"]
            n += 1
            methods.add(q["method"])
    return total, n, methods


def mats(e: dict) -> list[str]:
    return list(dict.fromkeys(m["name"] for m in e.get("materials") or [] if m.get("name")))


def storeys(els) -> str:
    s = list(dict.fromkeys(e.get("storey") for e in els if e.get("storey")))
    return ", ".join(s) if s else "pavimento não informado"


def method_txt(methods: set) -> str:
    return "; ".join(METHOD_PT[m] for m in sorted(methods) if m in METHOD_PT) or "—"


def fact(desc: str, value: str, els: list[dict], ctx: Ctx, methods: set | None = None) -> dict:
    return {"descricao": desc, "valor": value, "origem": ctx.src, "metodo": method_txt(methods or set()),
            "elementos": len(els), "global_ids": [e.get("global_id") for e in els if e.get("global_id")]}


def missing_summary(els: list[dict], label: str) -> list[str]:
    out = []
    counts = defaultdict(int)
    for e in els:
        for m in e.get("missing") or []:
            counts[m] += 1
    for m, n in counts.items():
        out.append(f"{label}: {n} de {len(els)} elemento(s) sem {m} no IFC.")
    return out


def _qty_phrase(els, names, label, unit, ctx, facts, d=2) -> str | None:
    total, n, methods = q_sum(els, names)
    if not n:
        return None
    partial = "" if n == len(els) else f" (somente {n} de {len(els)} elementos têm esse dado)"
    facts.append(fact(label, f"{num(total, d)} {unit}", els, ctx, methods))
    geo = " — valor calculado pela geometria, a conferir" if methods == {"geometrico"} else ""
    return f"{label} {num(total, d)} {unit}{partial}{geo}"


def _group(els, key):
    g = defaultdict(list)
    for e in els:
        g[key(e)].append(e)
    return g


# ------------------------------------------------------------------ capítulos
def ch_apresentacao(ctx: Ctx, project: dict, model: dict | None) -> dict:
    paras, facts, pending = [], [], []
    loc = (project.get("location") or "").strip()
    paras.append(f"O presente memorial descritivo refere-se ao projeto «{project['name']}»"
                 + (f", localizado em {loc}." if loc else "."))
    if not loc:
        pending.append("Informar a localização da obra (não cadastrada no projeto).")
    if model:
        h = model.get("header") or {}
        app = h.get("originating_system") or h.get("application")
        st = (model.get("summary") or {}).get("storeys") or []
        st_txt = "; ".join(f"{s['name']}" + (f" (cota {num(s['elevation_m'])} m)" if s.get("elevation_m") is not None else "")
                           for s in st if s["name"] != "(sem pavimento)")
        paras.append(f"As informações técnicas deste documento foram extraídas do modelo IFC «{model['original_filename']}» "
                     f"(versão {model['version']} no sistema, esquema {model['schema_name']}"
                     + (f", gerado por {app}" if app else "") + f"), que contém {model['n_elements']} elementos"
                     + (f" distribuídos nos pavimentos: {st_txt}." if st_txt else "."))
        facts.append(fact("Pavimentos do modelo", st_txt or "—", [], ctx, {"explicito"}))
    pending.append("Descrever o objeto da contratação e a finalidade da obra (informação que não consta no modelo IFC).")
    return {"paragraphs": paras, "facts": facts, "pending": pending, "tables": [],
            "query": "disposições gerais memorial descritivo normas ABNT fiscalização materiais"}


def ch_ambientes(ctx: Ctx) -> dict | None:
    sp = ctx.where(lambda e: e["ifc_class"] == "IfcSpace")
    if not sp:
        return None
    rows, facts, total, n_area = [], [], 0.0, 0
    for e in sorted(sp, key=lambda e: (ctx.storey_rank.get(e.get("storey"), 999), e.get("name") or "")):
        q = q_first(e, {"NetFloorArea", "GrossFloorArea", "Área de piso (malha 3D)"})
        if q:
            total += q["value"]
            n_area += 1
        rows.append([e.get("storey") or "—", e.get("long_name") or e.get("name") or "(sem nome)",
                     num(q["value"]) if q else "não informada", "IFC (geometria)" if q and q["method"] == "geometrico" else "IFC" if q else "—"])
    facts.append(fact("Área útil total dos ambientes", f"{num(total)} m²", sp, ctx, {"explicito"}))
    pending = [f"{len(sp) - n_area} ambiente(s) sem área no IFC."] if n_area < len(sp) else []
    return {"paragraphs": [f"Foram identificados {len(sp)} ambientes no modelo, com área útil total de {num(total)} m²"
                           + (f" (soma de {n_area} ambientes com área informada)" if n_area < len(sp) else "") + ", conforme o quadro a seguir."],
            "facts": facts, "pending": pending,
            "tables": [{"title": "Quadro de ambientes", "columns": ["Pavimento", "Ambiente", "Área útil (m²)", "Origem"], "rows": rows}],
            "query": "ambientes salas de aula sanitários circulação áreas"}


def _describe_groups(groups, ctx, facts, pending, label_fn, qty_specs, extra_fn=None):
    paras = []
    for key, els in groups.items():
        parts = [label_fn(key, els)]
        for names, label, unit in qty_specs:
            ph = _qty_phrase(els, names, label, unit, ctx, facts)
            if ph:
                parts.append(ph)
        if extra_fn:
            extra = extra_fn(els)
            if extra:
                parts += extra if isinstance(extra, list) else [extra]
        paras.append("; ".join(parts) + ".")
    return paras


def ch_fundacoes(ctx: Ctx) -> dict | None:
    els = ctx.where(lambda e: e["ifc_class"] in ("IfcFooting", "IfcPile"))
    if not els:
        return None
    facts, pending = [], missing_summary(els, "Fundações")
    groups = _group(els, lambda e: (e["ifc_class"], e.get("predefined_type"), ", ".join(mats(e)) or "material não informado"))

    def label(k, g):
        tipo = PT_TYPES.get(k[1] or "", "estacas" if k[0] == "IfcPile" else "elementos de fundação")
        return f"Fundações em {tipo}: {len(g)} unidade(s) em {k[2]}"

    def dims(g):
        vals = [{(q_first(e, {n}) or {}).get("value") for e in g} for n in ("Length", "Width", "Height")]
        if all(len(v) == 1 and None not in v for v in vals):
            L, W, H = (next(iter(v)) for v in vals)
            facts.append(fact("Dimensões das peças de fundação", f"{num(L)} × {num(W)} × {num(H)} m", g, ctx, {"explicito"}))
            return f"dimensões {num(L)} × {num(W)} × {num(H)} m (comprimento × largura × altura)"
        return None
    paras = _describe_groups(groups, ctx, facts, pending, label, [({"NetVolume", "GrossVolume", "Volume (malha 3D)"}, "volume total", "m³")], dims)
    pending.append("Confirmar a cota de assentamento e as características do solo (não constam no IFC).")
    return {"paragraphs": paras, "facts": facts, "pending": pending, "tables": [],
            "query": "fundações sapatas isoladas concreto armado lastro concreto magro cota de assentamento"}


def ch_estrutura_concreto(ctx: Ctx) -> dict | None:
    els = ctx.where(lambda e: e.get("discipline") == "Estrutura" and e["ifc_class"] not in ("IfcFooting", "IfcPile"))
    if not els:
        return None
    facts, pending = [], missing_summary(els, "Estrutura")
    names = {"IfcColumn": "Pilares", "IfcBeam": "Vigas", "IfcSlab": "Lajes", "IfcWall": "Paredes estruturais", "IfcMember": "Barras"}
    groups = _group(els, lambda e: (names.get(e["ifc_class"], e["ifc_class"]), ", ".join(mats(e)) or "material não informado"))
    paras = ["A estrutura identificada no modelo é composta pelos seguintes elementos:"]

    def thick(g):
        t = {round((q_first(e, {"Width", "Depth"}) or {}).get("value") or -1, 4) for e in g}
        if len(t) == 1 and -1 not in t and g[0]["ifc_class"].startswith("IfcSlab"):
            v = next(iter(t))
            facts.append(fact("Espessura das lajes", f"{cm(v)} cm", g, ctx, {"explicito"}))
            return f"espessura {cm(v)} cm"
        return None
    paras += _describe_groups(groups, ctx, facts, pending,
                              lambda k, g: f"{k[0]}: {len(g)} elemento(s) em {k[1]} ({storeys(g)})",
                              [({"NetArea", "GrossArea"}, "área total", "m²"),
                               ({"NetVolume", "GrossVolume", "Volume (malha 3D)"}, "volume total", "m³")], thick)
    pending.append("A resistência característica do concreto (fck), o aço das armaduras e os cobrimentos devem seguir o projeto estrutural (o IFC traz apenas o nome do material).")
    return {"paragraphs": paras, "facts": facts, "pending": pending, "tables": [],
            "query": "estrutura de concreto armado pilares vigas lajes formas armaduras cura concreto"}


def ch_estrutura_metalica(ctx: Ctx) -> dict | None:
    els = ctx.where(lambda e: e.get("discipline") == "Estrutura metálica")
    if not els:
        return None
    facts, pending = [], missing_summary(els, "Estrutura metálica")
    groups = _group(els, lambda e: (base_name(e.get("name")), ", ".join(mats(e)) or "material não informado", e["ifc_class"]))
    paras = ["A estrutura metálica identificada no modelo compreende:"]
    paras += _describe_groups(groups, ctx, facts, pending,
                              lambda k, g: f"{k[0]} ({k[2]}{', ' + PT_TYPES[g[0]['predefined_type']] if g[0].get('predefined_type') in PT_TYPES else ''}): "
                                           f"{len(g)} peça(s) em {k[1]} ({storeys(g)})",
                              [({"Length"}, "comprimento total", "m"), ({"NetWeight", "GrossWeight"}, "massa total", "kg")])
    pending.append("Perfis, ligações, proteção anticorrosiva e pintura devem seguir o projeto da estrutura metálica.")
    return {"paragraphs": paras, "facts": facts, "pending": pending, "tables": [],
            "query": "estrutura metálica cobertura tesouras terças perfis aço pintura anticorrosiva"}


def ch_vedacoes(ctx: Ctx) -> dict | None:
    els = ctx.where(lambda e: e["ifc_class"].startswith("IfcWall") and e.get("discipline") != "Estrutura")
    if not els:
        return None
    facts, pending = [], missing_summary(els, "Paredes")

    def key(e):
        ms = e.get("material_set") or {}
        return ms.get("name") or ", ".join(mats(e)) or "sem material informado"
    paras = []
    for k, g in _group(els, key).items():
        layers = [m for m in (g[0].get("materials") or []) if m.get("thickness_m")]
        comp = ""
        if layers:
            comp = "composição em camadas (do IFC): " + "; ".join(f"{m['name']} {cm(m['thickness_m'])} cm" for m in layers)
            tot = sum(m["thickness_m"] for m in layers)
            comp += f" — espessura total {cm(tot)} cm"
            facts.append(fact(f"Composição «{k}»", comp, g, ctx, {"explicito"}))
        ext = [e for e in g if (e.get("psets") or {}).get("Pset_WallCommon", {}).get("IsExternal") is True]
        fire = sorted({str((e.get("psets") or {}).get("Pset_WallCommon", {}).get("FireRating")) for e in g
                       if (e.get("psets") or {}).get("Pset_WallCommon", {}).get("FireRating")})
        parts = [f"Vedação «{k}»: {len(g)} parede(s) ({storeys(g)})"
                 + (f", sendo {len(ext)} externa(s)" if ext else "")]
        if comp:
            parts.append(comp)
        for names, label, unit in (({"Length"}, "comprimento total", "m"),
                                   ({"NetSideArea", "GrossSideArea", "Área lateral (malha 3D)"}, "área total de parede", "m²")):
            ph = _qty_phrase(g, names, label, unit, ctx, facts)
            if ph:
                parts.append(ph)
        if fire:
            parts.append(f"resistência ao fogo informada no IFC: {', '.join(fire)}")
            facts.append(fact(f"Resistência ao fogo «{k}»", ", ".join(fire), g, ctx, {"explicito"}))
        paras.append("; ".join(parts) + ".")
    pending.append("Traço/tipo de argamassa de assentamento, amarração e vergas/contravergas não constam no IFC.")
    return {"paragraphs": paras, "facts": facts, "pending": pending, "tables": [],
            "query": "alvenaria de vedação blocos cerâmicos argamassa de assentamento divisórias drywall gesso acartonado"}


def ch_esquadrias(ctx: Ctx) -> dict | None:
    els = ctx.where(lambda e: e["ifc_class"] in ("IfcDoor", "IfcWindow", "IfcCurtainWall"))
    if not els:
        return None
    facts, pending, rows = [], missing_summary(els, "Esquadrias"), []
    for (cls, tname), g in _group(els, lambda e: (e["ifc_class"], e.get("type_name") or base_name(e.get("name")))).items():
        w = {(q_first(e, {"OverallWidth"}) or {}).get("value") for e in g}
        h = {(q_first(e, {"OverallHeight"}) or {}).get("value") for e in g}
        dim = f"{num(next(iter(w)))} × {num(next(iter(h)))}" if len(w) == len(h) == 1 and None not in w | h else "variadas/não informadas"
        m = ", ".join(mats(g[0])) or "não informado"
        rows.append(["Porta" if cls == "IfcDoor" else "Janela" if cls == "IfcWindow" else "Fachada-cortina",
                     tname, str(len(g)), dim, m, storeys(g)])
        facts.append(fact(f"Esquadria «{tname}»", f"{len(g)} un · {dim} m · {m}", g, ctx, {"atributo"}))
    nd = sum(1 for e in els if e["ifc_class"] == "IfcDoor")
    nw = len(els) - nd
    return {"paragraphs": [f"Foram identificadas {nd} porta(s) e {nw} janela(s) no modelo, agrupadas por tipo no quadro a seguir "
                           "(dimensões: largura × altura, em metros, conforme atributos do IFC)."],
            "facts": facts, "pending": pending + ["Ferragens, acabamentos e desempenho (NBR 10821) não constam no IFC."],
            "tables": [{"title": "Quadro de esquadrias", "columns": ["Tipo", "Descrição (tipo no IFC)", "Qtde", "L × A (m)", "Material", "Pavimento"], "rows": rows}],
            "query": "esquadrias portas de madeira janelas de alumínio vidro temperado ferragens acessibilidade"}


def _coverings(ctx, ptypes, title_word, query, note) -> dict | None:
    els = ctx.where(lambda e: e["ifc_class"] == "IfcCovering" and (e.get("predefined_type") or "") in ptypes)
    if not els:
        return None
    facts, pending = [], missing_summary(els, title_word.capitalize())
    paras = _describe_groups(_group(els, lambda e: ", ".join(mats(e)) or "material não informado"), ctx, facts, pending,
                             lambda k, g: f"{k}: {len(g)} superfície(s) de {title_word} ("
                                          + "; ".join(dict.fromkeys(e.get('name') or '' for e in g))[:300] + ")",
                             [({"NetArea", "GrossArea", "Área de projeção (malha 3D)"}, "área total", "m²")])
    pending.append(note)
    return {"paragraphs": paras, "facts": facts, "pending": pending, "tables": [], "query": query}


def ch_pisos(ctx):
    return _coverings(ctx, {"FLOORING"}, "piso", "pisos porcelanato piso cerâmico antiderrapante contrapiso assentamento argamassa colante",
                      "Contrapiso, argamassa de assentamento, rejunte, rodapé e paginação não constam no IFC.")


def ch_revestimentos(ctx):
    return _coverings(ctx, {"CLADDING", "INSULATION", "MEMBRANE", "SKIRTINGBOARD", "MOLDING", "USERDEFINED", "NOTDEFINED", ""},
                      "revestimento", "revestimento cerâmico paredes áreas molhadas chapisco emboço reboco argamassa colante",
                      "Base (chapisco/emboço), argamassa colante, rejunte e paginação não constam no IFC.")


def ch_forros(ctx):
    return _coverings(ctx, {"CEILING"}, "forro", "forro de gesso acartonado estrutura metálica tabica",
                      "Sistema de fixação, altura do forro, juntas e acabamento não constam no IFC.")


def ch_cobertura(ctx: Ctx) -> dict | None:
    els = ctx.where(lambda e: e["ifc_class"] == "IfcRoof" or (e["ifc_class"] == "IfcCovering" and e.get("predefined_type") == "ROOFING")
                    or (e["ifc_class"].startswith("IfcSlab") and e.get("predefined_type") == "ROOF"))
    if not els:
        return None
    facts, pending = [], []
    paras = []
    for e in els:
        if e["ifc_class"] == "IfcRoof":
            paras.append(f"Cobertura «{e.get('name')}»" + (f" — tipo {e['predefined_type']} no IFC" if e.get("predefined_type") else "") + ".")
    paras += _describe_groups(_group([e for e in els if e["ifc_class"] != "IfcRoof"], lambda e: ", ".join(mats(e)) or "material não informado"),
                              ctx, facts, pending, lambda k, g: f"Telhamento em {k} ({storeys(g)})",
                              [({"NetArea", "GrossArea", "Área de projeção (malha 3D)"}, "área total", "m²")])
    if any(e.get("discipline") == "Estrutura metálica" for e in ctx.els):  # só consulta: não vincula ao capítulo
        paras.append("A estrutura de apoio da cobertura está descrita no capítulo de estrutura metálica.")
    pending.append("Inclinação, calhas, rufos e condutores não constam no IFC.")
    return {"paragraphs": paras, "facts": facts, "pending": pending, "tables": [],
            "query": "cobertura telhas metálicas termoacústicas cumeeira rufos calhas fixação"}


def ch_escadas(ctx: Ctx) -> dict | None:
    els = ctx.where(lambda e: e["ifc_class"] in ("IfcStair", "IfcStairFlight", "IfcRamp", "IfcRampFlight", "IfcRailing"))
    if not els:
        return None
    facts, pending = [], missing_summary(els, "Escadas/guarda-corpos")
    paras = _describe_groups(_group(els, lambda e: (e["ifc_class"], e.get("name"), ", ".join(mats(e)) or "material não informado")),
                             ctx, facts, pending, lambda k, g: f"«{k[1]}» ({k[0]}) em {k[2]}",
                             [({"Length"}, "comprimento", "m")])
    return {"paragraphs": paras, "facts": facts, "pending": pending, "tables": [],
            "query": "escadas guarda-corpos corrimãos altura acessibilidade"}


def _mep(ctx: Ctx, discipline: str, query: str, closing: str) -> dict | None:
    els = ctx.where(lambda e: e.get("discipline") == discipline)
    if not els:
        return None
    facts, pending = [], missing_summary([e for e in els if e.get("missing")], discipline) if any(e.get("missing") for e in els) else []
    paras = []
    by_sys = _group(els, lambda e: tuple(f"{s['name']}" + (f" ({s['predefined']})" if s.get("predefined") else "") for s in e.get("systems") or []) or ("sem sistema associado",))
    for sysk, g in by_sys.items():
        items = []
        for (cls, bn, pt), gg in _group(g, lambda e: (e["ifc_class"], base_name(e.get("name")), e.get("predefined_type"))).items():
            m = ", ".join(mats(gg[0]))
            ph = f"{len(gg)} × «{bn}»" + (f" ({PT_TYPES[pt]})" if pt in PT_TYPES else "") + (f" em {m}" if m else "")
            tot, n, methods = q_sum(gg, {"Length"})
            if n:
                ph += f", comprimento total {num(tot)} m"
                facts.append(fact(f"Comprimento «{bn}»", f"{num(tot)} m", gg, ctx, methods))
            dn = sorted({(e.get("psets") or {}).get(p, {}).get("NominalDiameter") for e in gg for p in (e.get("psets") or {})} - {None})
            if dn:
                ph += ", diâmetro nominal " + ", ".join(f"{num(d * 1000, 0)} mm" for d in dn if isinstance(d, (int, float)))
            items.append(ph)
            facts.append(fact(f"Quantidade «{bn}»", f"{len(gg)} un", gg, ctx, {"explicito"}))
        label = (f"Sistema {' / '.join(sysk)}" if sysk != ("sem sistema associado",)
                 else "Itens sem sistema associado no IFC")
        paras.append(f"{label}: " + "; ".join(items) + ".")
    pending.append(closing)
    return {"paragraphs": paras, "facts": facts, "pending": pending, "tables": [], "query": query}


def ch_hidro(ctx):
    return _mep(ctx, "Hidrossanitário", "instalações de água fria esgoto sanitário tubos PVC louças metais ralos sifonados ensaio estanqueidade",
                "Pressões, ensaios, caimentos e especificação de louças e metais devem seguir o projeto hidrossanitário.")


def ch_eletrica(ctx):
    return _mep(ctx, "Elétrica", "instalações elétricas baixa tensão quadro de distribuição disjuntores tomadas iluminação LED eletrocalha",
                "Circuitos, potências, condutores e proteções devem seguir o projeto elétrico (não constam no IFC).")


def ch_climatizacao(ctx):
    return _mep(ctx, "Climatização", "climatização ar-condicionado split exaustão drenos linhas frigorígenas",
                "Capacidades, cargas térmicas e trajetos de drenos/linhas devem seguir o projeto de climatização.")


COMPLEMENTARY = [  # capítulos usuais sem dados no IFC: só sugestões de referência
    ("servicos_preliminares", "Serviços preliminares", "serviços preliminares canteiro tapumes demolições remoções NR-18"),
    ("impermeabilizacao", "Impermeabilização", "impermeabilização áreas molhadas lajes manta asfáltica"),
    ("pintura", "Pintura", "pintura paredes internas selador massa corrida tinta acrílica"),
    ("limpeza", "Limpeza final", "limpeza final entrega da obra remoção de entulho"),
]

BUILDERS = [
    ("ambientes", "Quadro de ambientes", ch_ambientes),
    ("fundacoes", "Fundações", ch_fundacoes),
    ("estrutura", "Estrutura de concreto", ch_estrutura_concreto),
    ("estrutura_metalica", "Estrutura metálica", ch_estrutura_metalica),
    ("vedacoes", "Alvenarias e vedações", ch_vedacoes),
    ("revestimentos", "Revestimentos", ch_revestimentos),
    ("pisos", "Pisos", ch_pisos),
    ("forros", "Forros", ch_forros),
    ("esquadrias", "Esquadrias", ch_esquadrias),
    ("escadas", "Escadas e guarda-corpos", ch_escadas),
    ("cobertura", "Cobertura", ch_cobertura),
    ("hidro", "Instalações hidrossanitárias", ch_hidro),
    ("eletrica", "Instalações elétricas", ch_eletrica),
    ("climatizacao", "Climatização e exaustão", ch_climatizacao),
]


# ordem usual de um memorial descritivo de edificação
ORDER = ["apresentacao", "servicos_preliminares", "ambientes", "fundacoes", "estrutura", "estrutura_metalica",
         "vedacoes", "impermeabilizacao", "revestimentos", "pisos", "forros", "pintura", "esquadrias", "escadas",
         "cobertura", "hidro", "eletrica", "climatizacao", "limpeza"]


def build_all(elements: list[dict], project: dict, model: dict | None) -> list[dict]:
    """Todos os capítulos, na ordem usual. Capítulos sem nenhum elemento no IFC são omitidos,
    exceto os complementares (sem dados no IFC por natureza), que entram vazios com pendência."""
    src = f"IFC «{model['original_filename']}» v{model['version']}" if model else "projeto"
    order = [s["name"] for s in ((model or {}).get("summary") or {}).get("storeys") or []]
    ctx = Ctx(elements, src, order)
    found = {"apresentacao": {"key": "apresentacao", "title": "Apresentação", **ch_apresentacao(ctx, project, model)}}
    for key, title, query in COMPLEMENTARY:
        found[key] = _complementary(key, title, query)
    for key, title, fn in BUILDERS:
        ctx.used = {}
        r = fn(ctx)
        if r:
            found[key] = {"key": key, "title": title, **r, "element_ids": list(ctx.used)}
    out = [found[k] for k in ORDER if k in found]
    out.append(ch_pendencias(elements, out, model))
    return out


def _complementary(key, title, query) -> dict:
    return {"key": key, "title": title, "paragraphs": [], "facts": [], "tables": [], "query": query, "element_ids": [],
            "pending": ["Capítulo sem dados no modelo IFC: redija o texto ou insira um trecho de referência da biblioteca."]}


def ch_pendencias(elements: list[dict], chapters: list[dict], model: dict | None) -> dict:
    paras = ["Este capítulo reúne as informações necessárias ao memorial que não foram encontradas no modelo IFC. "
             "Elas devem ser obtidas nos projetos complementares ou confirmadas pelo responsável técnico antes da emissão final."]
    rows = []
    for c in chapters:
        for p in c.get("pending") or []:
            rows.append([c["title"], p])
    pend = [e for e in elements if e.get("discipline") in ("Pendente", "Instalações (indefinida)")]
    for e in pend:
        sug = e.get("suggestion")
        rows.append(["Classificação de elementos",
                     f"«{e.get('name') or '(sem nome)'}» ({e['ifc_class']}) sem disciplina definida"
                     + (f" — sugestão pelo nome: {sug['discipline']} (confirmar)" if sug else "")])
    return {"key": "pendencias", "title": "Pendências de informação", "paragraphs": paras, "facts": [],
            "pending": [], "tables": [{"title": "Informações a confirmar", "columns": ["Capítulo", "Pendência"], "rows": rows}],
            "query": "", "element_ids": [e["global_id"] for e in pend if e.get("global_id")]}
