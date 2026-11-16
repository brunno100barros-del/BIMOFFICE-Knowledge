"""Demonstração estática (GitHub Pages): arquivos gerados pelo sistema real, consistentes e sem segredos."""
import json
import re
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent / "frontend" / "demo"


def test_manifest_points_to_existing_files():
    man = json.loads((DEMO / "manifest.json").read_text(encoding="utf-8"))
    routes = man["routes"]
    for key in ("/api/config", "/api/library/stats", "/api/projects", "/api/memorials", "/api/search/status"):
        assert key in routes, key
    for route, f in routes.items():
        path = DEMO / f
        assert path.is_file(), (route, f)
        if f.endswith(".json"):
            json.loads(path.read_text(encoding="utf-8"))
    assert json.loads((DEMO / routes["/api/config"]).read_text(encoding="utf-8"))["demo"] is True


def test_demo_content_is_the_example_project():
    man = json.loads((DEMO / "manifest.json").read_text(encoding="utf-8"))["routes"]
    projects = json.loads((DEMO / man["/api/projects"]).read_text(encoding="utf-8"))
    assert [p["name"] for p in projects] == ["Escola SENAI - Bloco B (EXEMPLO)"]
    mem = json.loads((DEMO / man["/api/memorials/1"]).read_text(encoding="utf-8"))
    assert len(mem["chapters"]) >= 15 and all(c["status"] == "rascunho" for c in mem["chapters"])
    # cada trecho inserido mantém origem e texto original
    refs = [r for c in mem["chapters"] for r in c["inserted_refs"]]
    assert refs and all(r["original_text"] and r["section_path"] for r in refs)


def test_no_secrets_or_local_paths_in_demo():
    for f in DEMO.rglob("*.json"):
        t = f.read_text(encoding="utf-8")
        assert not re.search(r"(client_secret|api[_-]?key|BIMOFFICE_API_TOKEN *=|ghp_[A-Za-z0-9]{20})", t, re.I), f
        assert "/home/" not in t and "C:\\\\Users" not in t and "bimoffice_demo_" not in t, f
