"""
Gera docs/security-audit/relatorio-auditoria-seguranca.pdf a partir de
findings_data.py.

Uso:
    python -m venv .venv-audit
    .venv-audit/Scripts/activate  (Windows) ou source .venv-audit/bin/activate
    pip install reportlab
    python docs/security-audit/generate_report.py

Não depende de nada além do reportlab (já é dependência do projeto principal,
usado em app/utils/export.py) — sem instalação global, sem matplotlib.
"""

import sys
from collections import Counter
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table,
    TableStyle, NextPageTemplate, PageBreak, KeepTogether, HRFlowable,
)
from reportlab.graphics.shapes import Drawing, String, Circle
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.pdfgen import canvas as pdfcanvas

sys.path.insert(0, str(Path(__file__).parent))
from findings_data import (  # noqa: E402
    PROJECT_NAME, REPORT_DATE, AUDIT_COMMIT, STACK_SUMMARY, METHODOLOGY_NOTES,
    SEVERITY_COLORS, SEVERITY_LABELS, CATEGORY_LABELS,
    FINDINGS, NOT_APPLICABLE, STRENGTHS, RECOMMENDATIONS,
    REMEDIATION, REMEDIATION_DATE, EXTRA_FIXES,
)

OUT_PATH = Path(__file__).parent / "relatorio-auditoria-seguranca.pdf"
REPORT_TITLE = f"Relatório de Auditoria de Segurança — {PROJECT_NAME}"

PAGE_W, PAGE_H = A4
MARGIN = 2 * cm

INK = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#6B7280")
LIGHT_BG = colors.HexColor("#F3F4F6")
BORDER = colors.HexColor("#D1D5DB")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(
    name="CoverTitle", fontName="Helvetica-Bold", fontSize=24,
    leading=30, textColor=INK, spaceAfter=6, alignment=TA_LEFT,
))
styles.add(ParagraphStyle(
    name="CoverSub", fontName="Helvetica", fontSize=12,
    leading=16, textColor=MUTED, spaceAfter=4,
))
styles.add(ParagraphStyle(
    name="H1", fontName="Helvetica-Bold", fontSize=16, leading=20,
    textColor=INK, spaceBefore=14, spaceAfter=8,
))
styles.add(ParagraphStyle(
    name="H2", fontName="Helvetica-Bold", fontSize=12.5, leading=16,
    textColor=INK, spaceBefore=10, spaceAfter=6,
))
styles.add(ParagraphStyle(
    name="Body", fontName="Helvetica", fontSize=9.3, leading=13,
    textColor=INK, alignment=TA_LEFT,
))
styles.add(ParagraphStyle(
    name="BodySmall", fontName="Helvetica", fontSize=8.3, leading=11.5,
    textColor=INK,
))
styles.add(ParagraphStyle(
    name="Mono", fontName="Courier", fontSize=7.6, leading=10.2,
    textColor=INK, backColor=LIGHT_BG,
))
styles.add(ParagraphStyle(
    name="MonoIssue", fontName="Courier", fontSize=8, leading=11,
    textColor=INK,
))
styles.add(ParagraphStyle(
    name="TableCell", fontName="Helvetica", fontSize=8.2, leading=11,
    textColor=INK,
))
styles.add(ParagraphStyle(
    name="TableCellBold", fontName="Helvetica-Bold", fontSize=8.2, leading=11,
    textColor=INK,
))


def esc(text: str) -> str:
    """Escape &, < and > so reportlab's Paragraph mini-XML parser never
    interprets literal payload examples (e.g. <img onerror=...>) inside a
    finding's text as real markup tags."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def chip(text, hexcolor):
    """A small colored severity chip rendered as a 1-cell table."""
    t = Table([[text]], colWidths=[2.4 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(hexcolor)),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.6),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    return t


# ---------------------------------------------------------------------------
# Header / footer
# ---------------------------------------------------------------------------
def draw_header_footer(c: pdfcanvas.Canvas, doc):
    c.saveState()
    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    c.drawString(MARGIN, PAGE_H - 1.3 * cm, REPORT_TITLE)
    c.drawRightString(
        PAGE_W - MARGIN, PAGE_H - 1.3 * cm,
        f"Auditoria {REPORT_DATE} · Correções {REMEDIATION_DATE}"
    )
    c.setStrokeColor(BORDER)
    c.line(MARGIN, PAGE_H - 1.45 * cm, PAGE_W - MARGIN, PAGE_H - 1.45 * cm)

    c.line(MARGIN, 1.35 * cm, PAGE_W - MARGIN, 1.35 * cm)
    c.drawString(MARGIN, 1.0 * cm, f"{PROJECT_NAME} — Auditoria de Segurança")
    c.drawRightString(PAGE_W - MARGIN, 1.0 * cm, f"Página {doc.page}")
    c.restoreState()


def draw_cover(c: pdfcanvas.Canvas, doc):
    c.saveState()
    c.setFillColor(colors.HexColor("#111827"))
    c.rect(0, PAGE_H - 7.5 * cm, PAGE_W, 7.5 * cm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(MARGIN, PAGE_H - 3.0 * cm, "RELATÓRIO DE AUDITORIA DE SEGURANÇA")
    c.setFont("Helvetica-Bold", 22)
    c.drawString(MARGIN, PAGE_H - 4.2 * cm, PROJECT_NAME)
    c.setFont("Helvetica", 11)
    c.setFillColor(colors.HexColor("#D1D5DB"))
    c.drawString(MARGIN, PAGE_H - 5.2 * cm, f"Data: {REPORT_DATE}    •    Commit auditado: {AUDIT_COMMIT}")
    c.drawString(MARGIN, 1.0 * cm, f"Página {doc.page}")
    c.restoreState()


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def donut_by_severity(counts: dict) -> Drawing:
    order = ["critica", "alta", "media", "baixa", "informativa"]
    labels, values, chart_colors = [], [], []
    for key in order:
        n = counts.get(key, 0)
        if n:
            labels.append(f"{SEVERITY_LABELS.get(key, key)} ({n})")
            values.append(n)
            chart_colors.append(colors.HexColor(SEVERITY_COLORS[key]))

    d = Drawing(320, 200)
    pie = Pie()
    pie.x, pie.y = 50, 25
    pie.width, pie.height = 150, 150
    pie.data = values
    pie.labels = None
    pie.simpleLabels = False
    pie.sideLabels = False
    for i, c in enumerate(chart_colors):
        pie.slices[i].fillColor = c
        pie.slices[i].strokeColor = colors.white
        pie.slices[i].strokeWidth = 2
    d.add(pie)
    # Donut hole
    d.add(Circle(50 + 75, 25 + 75, 45, fillColor=colors.white, strokeColor=colors.white))
    d.add(String(50 + 75, 25 + 78, str(sum(values)), fontName="Helvetica-Bold",
                  fontSize=20, fillColor=INK, textAnchor="middle"))
    d.add(String(50 + 75, 25 + 62, "achados", fontName="Helvetica",
                  fontSize=8, fillColor=MUTED, textAnchor="middle"))

    ly = 165
    for lab, c in zip(labels, chart_colors):
        d.add(Circle(230, ly + 3, 4, fillColor=c, strokeColor=c))
        d.add(String(240, ly, lab, fontName="Helvetica", fontSize=8.5, fillColor=INK))
        ly -= 16
    return d


CATEGORY_SHORT_LABELS = {
    "cat1": "Isolamento",
    "cat2": "Permissão",
    "cat3": "IDOR",
    "cat4": "Chaves",
    "cat5": "XSS",
}


def bar_by_category(counts: dict) -> Drawing:
    cats = list(CATEGORY_LABELS.keys())
    values = [counts.get(c, 0) for c in cats]
    short_labels = [CATEGORY_SHORT_LABELS[c] for c in cats]

    d = Drawing(460, 210)
    bc = VerticalBarChart()
    bc.x, bc.y = 45, 35
    bc.width, bc.height = 390, 150
    bc.data = [values]
    bc.categoryAxis.categoryNames = short_labels
    bc.categoryAxis.labels.fontName = "Helvetica"
    bc.categoryAxis.labels.fontSize = 8.5
    bc.categoryAxis.labels.boxAnchor = "n"
    bc.categoryAxis.labels.dy = -4
    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = max(values + [1]) + 1
    bc.valueAxis.valueStep = 1
    bc.valueAxis.labels.fontName = "Helvetica"
    bc.valueAxis.labels.fontSize = 8
    bc.bars[0].fillColor = colors.HexColor("#2563EB")
    bc.barWidth = 14
    bc.groupSpacing = 10
    d.add(bc)
    return d


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------
def build_story():
    story = []

    # --- Capa -------------------------------------------------------------
    story.append(NextPageTemplate("cover"))
    story.append(Spacer(1, 8.2 * cm))
    story.append(Paragraph("Escopo auditado", styles["H2"]))
    story.append(Paragraph(
        "Código-fonte completo do backend (app/, main.py, scripts/, register.py, "
        "remove.py, export_logs.py) e do frontend servido (app/templates/*.html), "
        "arquivos de configuração (.env.example, config.yaml, app/config.py) e o "
        "histórico completo do repositório git (8 commits, branch única main). "
        "EPI-Detect-main/ (pasta de referência de outro projeto) foi excluída do "
        "escopo por não fazer parte da aplicação.", styles["Body"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Stack detectada", styles["H2"]))
    story.append(Paragraph(esc(STACK_SUMMARY), styles["Body"]))

    story.append(NextPageTemplate("normal"))
    story.append(PageBreak())

    story.append(Paragraph("Nota Metodológica — Mapeamento por Categoria", styles["H1"]))
    story.append(Paragraph(
        "Como cada categoria pedida na auditoria foi traduzida para o "
        "equivalente real desta stack (sem RLS/multi-tenant nativo):",
        styles["Body"]))
    story.append(Spacer(1, 4))
    for title, text in METHODOLOGY_NOTES:
        story.append(Paragraph(f"<b>{esc(title)}.</b> {esc(text)}", styles["BodySmall"]))
        story.append(Spacer(1, 5))

    # --- Resumo executivo ---------------------------------------------------
    sev_counts = Counter(f["severity"] for f in FINDINGS)
    cat_counts = Counter(f["category"] for f in FINDINGS)

    story.append(Paragraph("Resumo Executivo", styles["H1"]))
    total = len(FINDINGS)
    story.append(Paragraph(
        f"Foram identificados <b>{total} achados acionáveis</b>, além de "
        f"<b>{len(STRENGTHS)} pontos fortes verificados</b> e "
        f"<b>{len(NOT_APPLICABLE)} categorias documentadas como não aplicáveis</b> "
        "com justificativa baseada em código (não forçadas).", styles["Body"]))
    story.append(Paragraph(
        f'<font color="#059669"><b>&#10003; Situação em {esc(REMEDIATION_DATE)}: '
        f'todos os {total} achados foram corrigidos</b></font> — ver a seção '
        '"Situação das Correções". Os achados seguem descritos na íntegra neste '
        'relatório, sem remoção, para preservar o histórico da auditoria.',
        styles["Body"]))
    story.append(Spacer(1, 4))

    counts_rows = [["Severidade", "Qtd."]]
    for key in ["critica", "alta", "media", "baixa", "informativa"]:
        n = sev_counts.get(key, 0)
        if n:
            counts_rows.append([SEVERITY_LABELS[key], str(n)])
    counts_table = Table(counts_rows, colWidths=[4 * cm, 1.5 * cm])
    counts_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.6),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    charts_row = Table(
        [[counts_table, donut_by_severity(sev_counts)]],
        colWidths=[6.2 * cm, 10.8 * cm],
    )
    charts_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(charts_row)
    story.append(Spacer(1, 10))
    story.append(KeepTogether([
        Paragraph("Achados por categoria", styles["H2"]),
        bar_by_category(cat_counts),
    ]))

    story.append(PageBreak())

    # --- Pontos fortes / fracos --------------------------------------------
    story.append(Paragraph("Pontos Fortes Verificados", styles["H1"]))
    for title, where, text in STRENGTHS:
        story.append(KeepTogether([
            Paragraph(f'<font color="#059669"><b>&#10003; {esc(title)}</b></font> '
                      f'<font color="#6B7280" size="7.6">— {esc(where)}</font>',
                      styles["BodySmall"]),
            Paragraph(esc(text), styles["BodySmall"]),
            Spacer(1, 5),
        ]))

    story.append(Spacer(1, 6))
    story.append(Paragraph("Categorias Não Aplicáveis (com justificativa)", styles["H1"]))
    for item in NOT_APPLICABLE:
        story.append(KeepTogether([
            Paragraph(f'<b>{esc(CATEGORY_LABELS[item["category"]])}</b> — {esc(item["title"])}',
                      styles["BodySmall"]),
            Paragraph(esc(item["text"]), styles["BodySmall"]),
            Spacer(1, 5),
        ]))

    story.append(Spacer(1, 6))
    story.append(Paragraph("Pontos Fracos — Riscos Centrais", styles["H1"]))
    for f in FINDINGS:
        color = SEVERITY_COLORS[f["severity"]]
        story.append(KeepTogether([
            Table([[chip(SEVERITY_LABELS[f["severity"]], color),
                    Paragraph(f'<b>{esc(f["id"])} — {esc(f["title"])}</b>', styles["BodySmall"])]],
                  colWidths=[2.6 * cm, 13.5 * cm],
                  style=TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")])),
            Spacer(1, 5),
        ]))

    story.append(PageBreak())

    # --- Tabela de achados detalhados --------------------------------------
    story.append(Paragraph("Achados Detalhados por Categoria", styles["H1"]))
    by_cat = {}
    for f in FINDINGS:
        by_cat.setdefault(f["category"], []).append(f)

    for cat_key, label in CATEGORY_LABELS.items():
        items = by_cat.get(cat_key)
        story.append(Paragraph(label, styles["H2"]))
        if not items:
            na = next((n for n in NOT_APPLICABLE if n["category"] == cat_key), None)
            story.append(Paragraph(
                "Nenhum achado acionável — ver justificativa na seção "
                "'Categorias Não Aplicáveis'." if na else
                "Nenhum achado acionável identificado nesta categoria.",
                styles["BodySmall"]))
            story.append(Spacer(1, 6))
            continue

        rows = [["Severidade", "Arquivo:linha", "Descrição"]]
        for f in items:
            rows.append([
                chip(SEVERITY_LABELS[f["severity"]], SEVERITY_COLORS[f["severity"]]),
                Paragraph("<br/>".join(esc(loc) for loc in f["files"]), styles["TableCell"]),
                Paragraph(f'<b>{esc(f["id"])}.</b> {esc(f["title"])}', styles["TableCell"]),
            ])
        t = Table(rows, colWidths=[2.6 * cm, 5.2 * cm, 8.3 * cm], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8.4),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
        ]))
        story.append(t)
        story.append(Spacer(1, 10))

    story.append(PageBreak())

    # --- Evidência técnica completa (arquivo por arquivo) ------------------
    story.append(Paragraph("Evidência Técnica — Arquivo por Arquivo", styles["H1"]))
    for f in FINDINGS:
        evidence_html = esc(f["evidence"]).replace("\n", "<br/>").replace(" ", "&nbsp;")
        story.append(KeepTogether([
            Table([[chip(SEVERITY_LABELS[f["severity"]], SEVERITY_COLORS[f["severity"]]),
                    Paragraph(f'<b>{esc(f["id"])} — {esc(f["title"])}</b>', styles["H2"])]],
                  colWidths=[2.6 * cm, 13.5 * cm],
                  style=TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")])),
            Paragraph("<b>Arquivo(s):</b> " + esc("; ".join(f["files"])), styles["BodySmall"]),
            Spacer(1, 3),
            Paragraph(evidence_html, styles["Mono"]),
            Spacer(1, 3),
            Paragraph("<b>Por que é explorável:</b> " + esc(f["why"]), styles["BodySmall"]),
            Paragraph("<b>Impacto:</b> " + esc(f["impact"]), styles["BodySmall"]),
            Paragraph("<b>Correção sugerida:</b> " + esc(f["fix"]), styles["BodySmall"]),
            Paragraph(
                '<font color="#059669"><b>&#10003; Corrigido em '
                f'{esc(REMEDIATION_DATE)}:</b></font> '
                + esc(REMEDIATION[f["id"]]["text"]),
                styles["BodySmall"]),
        ]))
        story.append(Spacer(1, 12))
        story.append(HRFlowable(width="100%", color=BORDER, thickness=0.5))
        story.append(Spacer(1, 8))

    story.append(PageBreak())

    # --- Situação das correções ---------------------------------------------
    story.append(Paragraph("Situação das Correções", styles["H1"]))
    story.append(Paragraph(
        f"Todos os {len(FINDINGS)} achados foram corrigidos em "
        f"{esc(REMEDIATION_DATE)}, na mesma revisão em que este relatório foi "
        "entregue. Os achados seguem descritos acima na íntegra — nada foi "
        "removido — para que o histórico da auditoria continue auditável.",
        styles["Body"]))
    story.append(Spacer(1, 6))

    rows = [["Achado", "Severidade", "Situação"]]
    for f in FINDINGS:
        rows.append([
            Paragraph(f'<b>{esc(f["id"])}</b> — {esc(f["title"])}', styles["TableCell"]),
            chip(SEVERITY_LABELS[f["severity"]], SEVERITY_COLORS[f["severity"]]),
            Paragraph('<font color="#059669"><b>&#10003; Corrigido</b></font>',
                      styles["TableCell"]),
        ])
    t = Table(rows, colWidths=[9.5 * cm, 3.1 * cm, 3.5 * cm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.6),
        ("ALIGN", (1, 0), (2, 0), "CENTER"),
        ("LEFTPADDING", (1, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]))
    story.append(t)

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "Defeito adicional encontrado durante a validação das correções "
        "(fora do escopo original da auditoria):", styles["H2"]))
    for title, text in EXTRA_FIXES:
        story.append(Paragraph(f"<b>{esc(title)}</b>", styles["BodySmall"]))
        story.append(Paragraph(esc(text), styles["BodySmall"]))
        story.append(Spacer(1, 5))

    story.append(PageBreak())

    # --- Recomendações -------------------------------------------------------
    story.append(Paragraph("Recomendações Priorizadas", styles["H1"]))
    story.append(Paragraph(
        f'<font color="#059669"><b>&#10003; P1 a P5 implementadas em '
        f'{esc(REMEDIATION_DATE)}</b></font> — o texto original das '
        "recomendações é mantido abaixo; o detalhamento do que foi feito em cada "
        'uma está na seção "Situação das Correções".', styles["Body"]))
    story.append(Spacer(1, 6))
    rows = [["Prioridade", "Ação"]]
    for pri, text in RECOMMENDATIONS:
        rows.append([Paragraph(f"<b>{esc(pri)}</b>", styles["TableCell"]),
                     Paragraph(esc(text), styles["TableCell"])])
    t = Table(rows, colWidths=[2.2 * cm, 13.9 * cm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]))
    story.append(t)

    story.append(PageBreak())

    # --- Issues para o GitHub ------------------------------------------------
    story.append(Paragraph("Issues para o GitHub", styles["H1"]))
    story.append(Paragraph(
        "Texto completo, em Markdown, pronto para copiar e colar na criação de "
        "cada issue. Achados relacionados de baixo risco não foram agrupados "
        "nesta rodada porque cada achado abaixo já trata de um tema distinto. "
        f"<b>Atenção:</b> em {esc(REMEDIATION_DATE)} os cinco achados já foram "
        "corrigidos no código — as issues abaixo servem como registro/rastreio "
        "e devem ser abertas já com o comentário de correção, ou usadas apenas "
        "como referência histórica.",
        styles["Body"]))
    story.append(Spacer(1, 8))

    for i, f in enumerate(FINDINGS, start=1):
        md = render_issue_markdown(f)
        story.append(Paragraph(f"--- ISSUE {i} ---", styles["H2"]))
        for line in md.split("\n"):
            safe = esc(line).replace(" ", "&nbsp;")
            story.append(Paragraph(safe or "&nbsp;", styles["MonoIssue"]))
        story.append(Paragraph(f"--- FIM ISSUE {i} ---", styles["H2"]))
        story.append(Spacer(1, 10))

    return story


def render_issue_markdown(f: dict) -> str:
    labels = ", ".join(f["labels"])
    files_md = "\n".join(f"- `{loc}`" for loc in f["files"])
    accept_md = "\n".join(f"- [ ] {c}" for c in f["acceptance"])
    return (
        f'# [Segurança] {f["title"]}\n\n'
        f"**Labels sugeridas:** {labels}\n\n"
        f"## Descrição\n{f['why']}\n\n"
        f"## Evidência\n{files_md}\n\n"
        f"```\n{f['evidence']}\n```\n\n"
        f"## Impacto\n{f['impact']}\n\n"
        f"## Sugestão de correção\n{f['fix']}\n\n"
        f"## Critérios de aceite\n{accept_md}\n"
    )


def main():
    doc = BaseDocTemplate(
        str(OUT_PATH), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
        title=REPORT_TITLE, author="Auditoria de Segurança Automatizada",
    )
    frame_normal = Frame(MARGIN, MARGIN, PAGE_W - 2 * MARGIN,
                          PAGE_H - 2 * MARGIN - 0.8 * cm, id="normal")
    frame_cover = Frame(MARGIN, MARGIN, PAGE_W - 2 * MARGIN,
                         PAGE_H - 2 * MARGIN - 6.8 * cm, id="cover")

    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame_cover], onPage=draw_cover),
        PageTemplate(id="normal", frames=[frame_normal], onPage=draw_header_footer),
    ])

    doc.build(build_story())
    print(f"OK: {OUT_PATH} gerado.")


if __name__ == "__main__":
    main()
