"""Inventário técnico de um modelo IFC (resumo persistido junto ao modelo).

Somatórios são "calculados por regra": soma simples dos valores por método de origem
(explícito / atributo / geométrico NUNCA são misturados no mesmo total).
"""
from __future__ import annotations

from collections import Counter, defaultdict

SUM_UNITS = {"m", "m²", "m³", "kg", "un"}
# medidas lineares que SOMAM com sentido (comprimento total de paredes, perímetros).
# Altura, largura, espessura, profundidade NÃO são somadas (0,14 + 0,14 m de espessura não é 0,28 m).
ADDITIVE_LENGTHS = {"Length", "Perimeter", "GrossPerimeter", "NetPerimeter"}


def _additive(q: dict) -> bool:
    if q.get("unit") not in SUM_UNITS or not isinstance(q.get("value"), (int, float)):
        return False
    if (q.get("note") or "").startswith("unidade própria"):
        return False
    return q["unit"] != "m" or q.get("name") in ADDITIVE_LENGTHS


def build_summary(result: dict) -> dict:
    els = result["elements"]
    by_class = Counter(e["ifc_class"] for e in els)
    by_disc: dict[str, dict] = defaultdict(lambda: {"total": 0, "alta": 0, "média": 0, "baixa": 0})
    by_storey = Counter((e.get("storey") or "(sem pavimento)") for e in els)
    materials: dict[str, dict] = defaultdict(lambda: {"elements": 0, "classes": Counter()})
    totals: dict[tuple, dict] = {}
    missing = Counter()
    for e in els:
        d = by_disc[e.get("discipline") or "Pendente"]
        d["total"] += 1
        d[e.get("confidence") or "baixa"] += 1
        for name in dict.fromkeys(m.get("name") for m in e.get("materials") or [] if m.get("name")):
            materials[name]["elements"] += 1
            materials[name]["classes"][e["ifc_class"]] += 1
        for q in e.get("quantities") or []:
            if _additive(q):
                k = (e["ifc_class"], q["name"], q["unit"], q["method"])
                t = totals.setdefault(k, {"ifc_class": k[0], "quantity": k[1], "unit": k[2], "method": k[3],
                                          "total": 0.0, "elements": 0})
                t["total"] += q["value"]
                t["elements"] += 1
        for m in e.get("missing") or []:
            missing[m] += 1
    pending = [e for e in els if e.get("discipline") in ("Pendente", "Instalações (indefinida)")]
    return {
        "elements_total": len(els),
        "auxiliary_ignored": result.get("auxiliary_count", 0),
        "classes": dict(by_class.most_common()),
        "disciplines": dict(sorted(by_disc.items(), key=lambda kv: -kv[1]["total"])),
        "storeys": [{**s, "elements": by_storey.get(s["name"], 0)} for s in result.get("storeys", [])]
                   + ([{"name": "(sem pavimento)", "elevation_m": None, "elements": by_storey["(sem pavimento)"]}]
                      if by_storey.get("(sem pavimento)") else []),
        "materials": [{"name": k, "elements": v["elements"], "classes": dict(v["classes"])}
                      for k, v in sorted(materials.items(), key=lambda kv: -kv[1]["elements"])],
        "quantity_totals": sorted(({**t, "total": round(t["total"], 4)} for t in totals.values()),
                                  key=lambda t: (t["ifc_class"], t["quantity"], t["method"])),
        "missing_info": dict(missing.most_common()),
        "pending_classification": len(pending),
        "elements_with_suggestion": sum(1 for e in els if e.get("suggestion")),
        "read_errors": sum(1 for e in els if e.get("read_error")),
        "geometry": result.get("geometry"),
        "warnings": result.get("warnings", []),
        "totals_method": "Somatório por regra dos valores de cada elemento, separado por método de origem. "
                         "Só quantidades aditivas (área, volume, comprimento, massa, contagem); "
                         "alturas, larguras e espessuras não são somadas.",
    }
