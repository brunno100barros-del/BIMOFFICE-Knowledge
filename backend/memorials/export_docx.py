"""Exportação do memorial para Word (python-docx).

- Só o conteúdo do memorial: títulos, textos e quadros. NÃO exporta dados internos de pesquisa
  (relevância, sugestões, GlobalIds, métodos).
- Minuta: cabeçalho "MINUTA — NÃO REVISADA" em todas as páginas.
- Limitação: estilo institucional simples (Arial 11, títulos numerados). Importar um MODELO DOCX
  com estilos/cabeçalhos da instituição fica para uma próxima etapa.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor


def _page_number(paragraph) -> None:
    run = paragraph.add_run()
    for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)


def build_docx(memorial: dict, project: dict, draft: bool) -> bytes:
    d = Document()
    normal = d.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(6)
    for lvl in (1, 2):
        st = d.styles[f"Heading {lvl}"]
        st.font.name = "Arial"
        st.font.color.rgb = RGBColor(0x1F, 0x2A, 0x44)
        st.font.size = Pt(13 if lvl == 1 else 11)

    sec = d.sections[0]
    head = sec.header.paragraphs[0]
    head.text = ("MINUTA — NÃO REVISADA · " if draft else "") + memorial["title"]
    head.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for r in head.runs:
        r.font.size = Pt(8)
        if draft:
            r.font.bold = True
            r.font.color.rgb = RGBColor(0xB4, 0x23, 0x18)
    foot = sec.footer.paragraphs[0]
    foot.text = f"{project['name']} — página "
    foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _page_number(foot)
    for r in foot.runs:
        r.font.size = Pt(8)

    t = d.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = t.add_run(memorial["title"].upper())
    run.bold = True
    run.font.size = Pt(16)
    sub = d.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.add_run(project["name"] + (f" — {project['location']}" if project.get("location") else "")).font.size = Pt(11)
    dt = d.add_paragraph(date.today().strftime("%d/%m/%Y"))
    dt.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if draft:
        w = d.add_paragraph()
        w.alignment = WD_ALIGN_PARAGRAPH.CENTER
        wr = w.add_run("MINUTA PARA REVISÃO — documento ainda não aprovado pelo responsável técnico.")
        wr.bold = True
        wr.font.color.rgb = RGBColor(0xB4, 0x23, 0x18)

    for n, c in enumerate(memorial["chapters"], 1):
        d.add_heading(f"{n} {c['title'].upper()}", level=1)
        paras = [p.strip() for p in (c["text"] or "").split("\n\n") if p.strip()]
        if not paras and not c["tables"]:
            p = d.add_paragraph("[Capítulo sem texto]" if draft else "")
            if draft:
                p.runs[0].italic = True
        for ptxt in paras:
            p = d.add_paragraph(ptxt.replace("\n", " "))
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        for tb in c["tables"]:
            if not tb.get("rows"):
                continue
            cap = d.add_paragraph()
            cap.add_run(tb.get("title") or "").bold = True
            table = d.add_table(rows=1, cols=len(tb["columns"]))
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            for i, col in enumerate(tb["columns"]):
                cell = table.rows[0].cells[i]
                cell.text = str(col)
                for r in cell.paragraphs[0].runs:
                    r.bold = True
                    r.font.size = Pt(9)
            for row in tb["rows"]:
                cells = table.add_row().cells
                for i, v in enumerate(row[: len(tb["columns"])]):
                    cells[i].text = str(v)
                    for r in cells[i].paragraphs[0].runs:
                        r.font.size = Pt(9)
            d.add_paragraph()
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()
