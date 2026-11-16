"""Memorial descritivo em elaboração: geração por capítulos, edição, aprovação e histórico.

Regras do CLAUDE.md aplicadas aqui:
- (2) Conteúdo da biblioteca NUNCA entra sozinho: fica em `suggestions` até o usuário clicar em inserir.
- (3) Todo trecho inserido guarda origem e texto ORIGINAL (`inserted_refs`); `generated_text` (original
      do IFC) e `text` (adaptado) ficam separados.
- (4) Exportação final só com todos os capítulos aprovados (revisão humana); a minuta é marcada como tal.
- (8) Editar o memorial nunca altera a biblioteca nem o IFC.
"""
from __future__ import annotations

import json
import logging
import re

from backend.database.db import get_conn
from backend.memorials.chapters import build_all
from backend.projects import service as projects

log = logging.getLogger("bimoffice.memorials")


class MemorialError(Exception):
    pass


class NotFound(MemorialError):
    pass


class NotApproved(MemorialError):
    pass


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False)


JSON_COLS = ("facts", "pending", "tables_json", "suggestions", "inserted_refs")


def _chapter_row(r) -> dict:
    d = dict(r)
    for k in JSON_COLS:
        d[k] = json.loads(d[k] or "[]")
    d["tables"] = d.pop("tables_json")
    d["edited"] = d["text"].strip() != d["generated_text"].strip()
    return d


def _version(conn, cid: int, event: str, title: str, text: str) -> None:
    conn.execute("INSERT INTO memorial_versions(chapter_id, event, title, text) VALUES (?,?,?,?)",
                 (cid, event, title, text))


def _suggest(query: str, limit: int = 3) -> list[dict]:
    """Trechos de referência da biblioteca (pesquisa híbrida E5 + FTS5). Só sugestões."""
    if not query:
        return []
    try:
        from backend.semantic_search import hybrid
        res = hybrid.search(query, limit=limit)
    except Exception as e:  # pesquisa indisponível não impede gerar o memorial
        log.warning("Sugestões indisponíveis: %s", e)
        return []
    return [{"chunk_id": r["chunk_id"], "document_id": r["document_id"], "document_title": r["document_title"],
             "original_filename": r.get("original_filename"), "unit": r.get("unit"), "project": r.get("project"),
             "section_path": r["section_path"], "text": r["text"], "relative_relevance": r["relative_relevance"],
             "found_by": r["found_by"]} for r in res["results"]]


def _text(paragraphs: list[str]) -> str:
    return "\n\n".join(p for p in paragraphs if p)


# ------------------------------------------------------------------ criação
def create_memorial(project_id: int, model_id: int | None = None, title: str | None = None) -> dict:
    project = projects.get_project(project_id)
    models = projects.list_models(project_id)
    model = None
    if model_id is not None:
        model = next((m for m in models if m["id"] == model_id), None)
        if not model:
            raise NotFound("Modelo IFC não encontrado neste projeto.")
    elif models:
        model = models[0]
    elements = []
    if model:
        with get_conn() as conn:
            elements = [json.loads(r["data"]) for r in conn.execute(
                "SELECT data FROM ifc_elements WHERE model_id=? ORDER BY id", (model["id"],))]
    chapters = build_all(elements, project, model)
    title = (title or f"Memorial descritivo — {project['name']}").strip()
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO memorials(project_id, model_id, title) VALUES (?,?,?)",
                           (project_id, model["id"] if model else None, title))
        mid = cur.lastrowid
        for i, c in enumerate(chapters):
            gen = _text(c["paragraphs"])
            cur = conn.execute(
                """INSERT INTO memorial_chapters(memorial_id, position, key, title, generated_text, text, facts,
                   pending, tables_json, suggestions, query) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (mid, i, c["key"], c["title"], gen, gen, _j(c["facts"]), _j(c["pending"]), _j(c["tables"]),
                 _j(_suggest(c.get("query", ""))), c.get("query", "")))
            _version(conn, cur.lastrowid, "gerado a partir do IFC", c["title"], gen)
        projects.history(project_id, "memorial gerado", {"memorial": title, "capítulos": len(chapters),
                                                          "modelo": model["original_filename"] if model else None}, conn)
    return get_memorial(mid)


def get_memorial(mid: int) -> dict:
    with get_conn() as conn:
        m = conn.execute("SELECT * FROM memorials WHERE id=? AND deleted_at IS NULL", (mid,)).fetchone()
        if not m:
            raise NotFound("Memorial não encontrado.")
        chs = conn.execute("SELECT * FROM memorial_chapters WHERE memorial_id=? ORDER BY position, id", (mid,)).fetchall()
    d = dict(m)
    d["chapters"] = [_chapter_row(c) for c in chs]
    d["approved"] = sum(1 for c in d["chapters"] if c["status"] == "aprovado")
    d["ready_for_final"] = bool(d["chapters"]) and d["approved"] == len(d["chapters"])
    return d


def list_memorials(project_id: int) -> list[dict]:
    projects.get_project(project_id)
    with get_conn() as conn:
        rows = conn.execute("""SELECT m.*, COUNT(c.id) AS n_chapters,
                               SUM(CASE WHEN c.status='aprovado' THEN 1 ELSE 0 END) AS n_approved
                               FROM memorials m LEFT JOIN memorial_chapters c ON c.memorial_id=m.id
                               WHERE m.project_id=? AND m.deleted_at IS NULL GROUP BY m.id ORDER BY m.id DESC""",
                            (project_id,)).fetchall()
    return [dict(r) for r in rows]


def list_all() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""SELECT m.*, p.name AS project_name, COUNT(c.id) AS n_chapters,
                               SUM(CASE WHEN c.status='aprovado' THEN 1 ELSE 0 END) AS n_approved
                               FROM memorials m JOIN projects p ON p.id=m.project_id
                               LEFT JOIN memorial_chapters c ON c.memorial_id=m.id
                               WHERE m.deleted_at IS NULL AND p.deleted_at IS NULL
                               GROUP BY m.id, p.name ORDER BY m.updated_at DESC, m.id DESC""").fetchall()
    from backend import auth
    allowed = auth.accessible_project_ids(auth.user())
    return [dict(r) for r in rows if allowed is None or r["project_id"] in allowed]


def delete_memorial(mid: int) -> None:
    m = get_memorial(mid)
    with get_conn() as conn:
        conn.execute("UPDATE memorials SET deleted_at=datetime('now') WHERE id=?", (mid,))
        projects.history(m["project_id"], "memorial excluído", {"memorial": m["title"]}, conn)


def rename_memorial(mid: int, title: str) -> dict:
    if not (title or "").strip():
        raise MemorialError("O título não pode ficar vazio.")
    get_memorial(mid)
    with get_conn() as conn:
        conn.execute("UPDATE memorials SET title=?, updated_at=datetime('now') WHERE id=?", (title.strip(), mid))
    return get_memorial(mid)


# ------------------------------------------------------------------ capítulos
def get_chapter(cid: int) -> dict:
    with get_conn() as conn:
        r = conn.execute("""SELECT c.* FROM memorial_chapters c JOIN memorials m ON m.id=c.memorial_id
                            WHERE c.id=? AND m.deleted_at IS NULL""", (cid,)).fetchone()
    if not r:
        raise NotFound("Capítulo não encontrado.")
    return _chapter_row(r)


def _touch(conn, memorial_id: int) -> None:
    conn.execute("UPDATE memorials SET updated_at=datetime('now') WHERE id=?", (memorial_id,))


def update_chapter(cid: int, text: str | None = None, title: str | None = None) -> dict:
    c = get_chapter(cid)
    new_text = c["text"] if text is None else text.replace("\r\n", "\n").strip()
    new_title = c["title"] if title is None else title.strip()
    if not new_title:
        raise MemorialError("O título do capítulo não pode ficar vazio.")
    if new_text == c["text"] and new_title == c["title"]:
        return c
    with get_conn() as conn:
        # alterar um capítulo aprovado o devolve para rascunho (precisa de nova revisão)
        conn.execute("""UPDATE memorial_chapters SET text=?, title=?, status='rascunho', updated_at=datetime('now')
                        WHERE id=?""", (new_text, new_title, cid))
        _version(conn, cid, "editado pelo usuário", new_title, new_text)
        _touch(conn, c["memorial_id"])
    return get_chapter(cid)


def set_status(cid: int, approved: bool) -> dict:
    c = get_chapter(cid)
    st = "aprovado" if approved else "rascunho"
    with get_conn() as conn:
        conn.execute("UPDATE memorial_chapters SET status=?, updated_at=datetime('now') WHERE id=?", (st, cid))
        _version(conn, cid, "aprovado" if approved else "reaberto para revisão", c["title"], c["text"])
        _touch(conn, c["memorial_id"])
    return get_chapter(cid)


def insert_reference(cid: int, chunk_id: int) -> dict:
    """Insere (por pedido do usuário) um trecho da biblioteca no fim do capítulo, guardando a origem."""
    c = get_chapter(cid)
    with get_conn() as conn:
        r = conn.execute("""SELECT ch.id, ch.text, ch.section_path, d.id AS document_id, d.title, d.original_filename,
                            d.unit, d.project FROM chunks ch JOIN documents d ON d.id=ch.document_id
                            WHERE ch.id=? AND d.deleted_at IS NULL""", (chunk_id,)).fetchone()
    if not r:
        raise NotFound("Trecho de referência não encontrado (o documento pode ter sido excluído ou reindexado).")
    original = r["text"]
    # o trecho começa pelo título da seção de origem: no memorial fica só o corpo
    body = "\n".join(original.split("\n")[1:]).strip() if "\n" in original else original
    ref = {"chunk_id": r["id"], "document_id": r["document_id"], "document_title": r["title"],
           "original_filename": r["original_filename"], "unit": r["unit"], "project": r["project"],
           "section_path": r["section_path"], "original_text": original, "inserted_text": body}
    new_text = (c["text"] + "\n\n" + body).strip() if c["text"] else body
    with get_conn() as conn:
        conn.execute("""UPDATE memorial_chapters SET text=?, inserted_refs=?, status='rascunho',
                        updated_at=datetime('now') WHERE id=?""", (new_text, _j(c["inserted_refs"] + [ref]), cid))
        _version(conn, cid, f"trecho de referência inserido: {r['title']} › {r['section_path']}", c["title"], new_text)
        _touch(conn, c["memorial_id"])
    return get_chapter(cid)


def refresh_suggestions(cid: int, query: str | None = None) -> dict:
    c = get_chapter(cid)
    q = (query or c["query"] or c["title"]).strip()
    with get_conn() as conn:
        conn.execute("UPDATE memorial_chapters SET suggestions=?, query=? WHERE id=?", (_j(_suggest(q, 5)), q, cid))
    return get_chapter(cid)


def regenerate_chapter(cid: int, replace_text: bool = False) -> dict:
    """Recalcula o texto original a partir do IFC atual. Só substitui o texto editado se o usuário pedir."""
    c = get_chapter(cid)
    m = get_memorial(c["memorial_id"])
    project = projects.get_project(m["project_id"])
    model = projects.get_model(m["model_id"]) if m["model_id"] else None
    elements = []
    if model:
        with get_conn() as conn:
            elements = [json.loads(r["data"]) for r in conn.execute(
                "SELECT data FROM ifc_elements WHERE model_id=? ORDER BY id", (model["id"],))]
    fresh = next((x for x in build_all(elements, project, model) if x["key"] == c["key"]), None)
    if fresh is None:
        raise MemorialError("Este capítulo não pode ser regerado (criado pelo usuário ou sem dados no modelo).")
    gen = _text(fresh["paragraphs"])
    text = gen if replace_text or not c["edited"] else c["text"]
    with get_conn() as conn:
        conn.execute("""UPDATE memorial_chapters SET generated_text=?, text=?, facts=?, pending=?, tables_json=?,
                        status=CASE WHEN ?=1 THEN 'rascunho' ELSE status END, updated_at=datetime('now') WHERE id=?""",
                     (gen, text, _j(fresh["facts"]), _j(fresh["pending"]), _j(fresh["tables"]),
                      1 if text != c["text"] else 0, cid))
        _version(conn, cid, "regerado a partir do IFC" + (" (texto substituído)" if text != c["text"] else ""), c["title"], text)
    return get_chapter(cid)


def add_chapter(mid: int, title: str, after_id: int | None = None) -> dict:
    if not (title or "").strip():
        raise MemorialError("Informe o título do capítulo.")
    m = get_memorial(mid)
    pos = len(m["chapters"])
    if after_id is not None:
        idx = next((i for i, c in enumerate(m["chapters"]) if c["id"] == after_id), None)
        pos = (idx + 1) if idx is not None else pos
    with get_conn() as conn:
        conn.execute("UPDATE memorial_chapters SET position=position+1 WHERE memorial_id=? AND position>=?", (mid, pos))
        cur = conn.execute("""INSERT INTO memorial_chapters(memorial_id, position, key, title, pending)
                              VALUES (?,?,?,?,?)""", (mid, pos, "custom", title.strip(),
                                                      _j(["Capítulo criado pelo usuário: redija o texto."])))
        _version(conn, cur.lastrowid, "capítulo criado", title.strip(), "")
        _touch(conn, mid)
    _renumber(mid)
    return get_chapter(cur.lastrowid)


def _renumber(mid: int) -> None:
    with get_conn() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM memorial_chapters WHERE memorial_id=? ORDER BY position, id", (mid,))]
        conn.executemany("UPDATE memorial_chapters SET position=? WHERE id=?", [(i, cid) for i, cid in enumerate(ids)])


def move_chapter(cid: int, direction: int) -> dict:
    c = get_chapter(cid)
    m = get_memorial(c["memorial_id"])
    ids = [x["id"] for x in m["chapters"]]
    i = ids.index(cid)
    j = max(0, min(len(ids) - 1, i + (1 if direction > 0 else -1)))
    ids[i], ids[j] = ids[j], ids[i]
    with get_conn() as conn:
        conn.executemany("UPDATE memorial_chapters SET position=? WHERE id=?", [(k, x) for k, x in enumerate(ids)])
        _touch(conn, m["id"])
    return get_memorial(m["id"])


def delete_chapter(cid: int) -> dict:
    c = get_chapter(cid)
    with get_conn() as conn:
        conn.execute("DELETE FROM memorial_chapters WHERE id=?", (cid,))
        projects.history(get_memorial(c["memorial_id"])["project_id"], "capítulo removido do memorial",
                         {"capítulo": c["title"], "texto": c["text"][:500]}, conn)
        _touch(conn, c["memorial_id"])
    _renumber(c["memorial_id"])
    return get_memorial(c["memorial_id"])


def chapter_history(cid: int) -> list[dict]:
    get_chapter(cid)
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM memorial_versions WHERE chapter_id=? ORDER BY id DESC", (cid,))]


def export_docx(mid: int, draft: bool) -> tuple[bytes, str]:
    from backend.memorials.export_docx import build_docx
    m = get_memorial(mid)
    if not draft and not m["ready_for_final"]:
        raise NotApproved(f"Exportação final exige todos os capítulos aprovados "
                          f"({m['approved']} de {len(m['chapters'])}). Use a minuta para revisão.")
    project = projects.get_project(m["project_id"])
    data = build_docx(m, project, draft)
    # nome de arquivo seguro em qualquer sistema: sem acentos/travessões e sem caracteres proibidos no Windows
    import unicodedata
    safe = unicodedata.normalize("NFKD", m["title"].replace("—", "-").replace("–", "-"))
    safe = "".join(ch for ch in safe if not unicodedata.combining(ch))
    safe = re.sub(r'[\\/:*?"<>|]+', "-", safe)
    safe = re.sub(r"\s+", " ", safe)[:100].strip(" .")
    name = f"{safe}{' - MINUTA' if draft else ''}.docx"
    with get_conn() as conn:
        projects.history(m["project_id"], "memorial exportado (DOCX)",
                         {"memorial": m["title"], "tipo": "minuta" if draft else "final"}, conn)
    return data, name
