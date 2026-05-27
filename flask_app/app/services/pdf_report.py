"""Professional PDF report generator for AI detection and plagiarism results.

Uses ReportLab (already installed). Returns a bytes object containing the PDF.
"""
from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# ── Brand colours ──────────────────────────────────────────────────────────────
NAVY      = colors.HexColor("#0f1e35")
NAVY_MID  = colors.HexColor("#1a2d4e")
NAVY_LITE = colors.HexColor("#2a4070")
ACCENT    = colors.HexColor("#4f8ef7")
GREEN     = colors.HexColor("#22c55e")
YELLOW    = colors.HexColor("#f59e0b")
RED       = colors.HexColor("#ef4444")
GREY_LITE = colors.HexColor("#f1f5f9")
GREY_MID  = colors.HexColor("#94a3b8")
WHITE     = colors.white
BLACK     = colors.HexColor("#0f172a")

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm


def _score_color(pct: float) -> colors.HexColor:
    if pct >= 70:
        return RED
    if pct >= 40:
        return YELLOW
    return GREEN


def _bar_table(label_a: str, val_a: float, color_a,
               label_b: str, val_b: float, color_b,
               width: float) -> Table:
    """Two-column percentage bar."""
    bar_w = width - 40 * mm
    data = [[
        Paragraph(f"<b>{label_a}</b>", ParagraphStyle("bl", fontSize=9, textColor=GREY_MID)),
        Paragraph(f"<b>{label_b}</b>", ParagraphStyle("br", fontSize=9, textColor=GREY_MID,
                                                       alignment=TA_RIGHT)),
    ]]
    t = Table(data, colWidths=[bar_w / 2, bar_w / 2])
    t.setStyle(TableStyle([("ALIGN", (0, 0), (0, 0), "LEFT"),
                            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return t


def _section_title(text: str) -> Paragraph:
    return Paragraph(
        text,
        ParagraphStyle("sec", fontSize=11, fontName="Helvetica-Bold",
                       textColor=NAVY, spaceAfter=4, spaceBefore=10,
                       borderPad=0),
    )


# ──────────────────────────────────────────────────────────────────────────────
#  AI DETECTION REPORT
# ──────────────────────────────────────────────────────────────────────────────

def build_ai_report(
    ai_score: float,
    human_pct: float,
    detectors: list,
    words: int,
    text_excerpt: str = "",
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=15 * mm, bottomMargin=20 * mm,
    )

    content_width = PAGE_W - 2 * MARGIN
    story = []

    # ── HEADER ─────────────────────────────────────────────────────────────────
    header_data = [[
        Paragraph("<font color='white'><b>Smart Study Guides</b></font>",
                  ParagraphStyle("h1", fontSize=14, fontName="Helvetica-Bold",
                                 textColor=WHITE)),
        Paragraph(
            "<font color='white'><b>AI Detection Report</b></font>",
            ParagraphStyle("h2", fontSize=14, fontName="Helvetica-Bold",
                           textColor=WHITE, alignment=TA_RIGHT),
        ),
    ]]
    hdr = Table(header_data, colWidths=[content_width / 2, content_width / 2])
    hdr.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 5 * mm))

    # ── META ───────────────────────────────────────────────────────────────────
    now = datetime.now().strftime("%B %d, %Y  %H:%M")
    meta_data = [[
        Paragraph(f"Generated: {now}",
                  ParagraphStyle("m1", fontSize=8, textColor=GREY_MID)),
        Paragraph(f"Words analyzed: {words:,}",
                  ParagraphStyle("m2", fontSize=8, textColor=GREY_MID, alignment=TA_RIGHT)),
    ]]
    mt = Table(meta_data, colWidths=[content_width / 2, content_width / 2])
    mt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(mt)
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY_MID,
                            spaceAfter=6, spaceBefore=4))

    # ── OVERALL SCORES ─────────────────────────────────────────────────────────
    story.append(_section_title("Overall Result"))

    ai_color  = _score_color(ai_score)
    score_data = [[
        Paragraph(
            f"<font color='#{ai_color.hexval()[2:]}' size='32'><b>{ai_score:.1f}%</b></font><br/>"
            f"<font color='#94a3b8' size='9'>AI Content</font>",
            ParagraphStyle("sc", alignment=TA_CENTER, leading=36),
        ),
        Paragraph(
            f"<font color='#22c55e' size='32'><b>{human_pct:.1f}%</b></font><br/>"
            f"<font color='#94a3b8' size='9'>Human Content</font>",
            ParagraphStyle("sc2", alignment=TA_CENTER, leading=36),
        ),
    ]]
    sc = Table(score_data, colWidths=[content_width / 2, content_width / 2])
    sc.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GREY_LITE),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("BOX", (0, 0), (-1, -1), 0.5, GREY_MID),
        ("LINEBEFORE", (1, 0), (1, 0), 0.5, GREY_MID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(sc)
    story.append(Spacer(1, 4 * mm))

    # Verdict
    if ai_score >= 70:
        vtext, vcolor = "🚨  HIGH — Likely to be flagged as AI-generated", RED
    elif ai_score >= 40:
        vtext, vcolor = "⚠️  MODERATE — Consider humanizing before submission", YELLOW
    else:
        vtext, vcolor = "✅  LOW — Text appears to be human-written", GREEN

    vd = Table([[Paragraph(
        f"<font color='#{vcolor.hexval()[2:]}' size='10'><b>{vtext}</b></font>",
        ParagraphStyle("vd", alignment=TA_CENTER),
    )]], colWidths=[content_width])
    vd.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GREY_LITE),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BOX", (0, 0), (-1, -1), 0.5, GREY_MID),
    ]))
    story.append(vd)

    # ── DETECTOR BREAKDOWN ─────────────────────────────────────────────────────
    story.append(Spacer(1, 5 * mm))
    story.append(_section_title("Detector Breakdown"))

    det_header = [
        Paragraph("<b>Detector</b>",
                  ParagraphStyle("dh", fontSize=9, fontName="Helvetica-Bold",
                                 textColor=WHITE)),
        Paragraph("<b>AI Score</b>",
                  ParagraphStyle("dh2", fontSize=9, fontName="Helvetica-Bold",
                                 textColor=WHITE, alignment=TA_CENTER)),
        Paragraph("<b>Human Score</b>",
                  ParagraphStyle("dh3", fontSize=9, fontName="Helvetica-Bold",
                                 textColor=WHITE, alignment=TA_CENTER)),
        Paragraph("<b>Verdict</b>",
                  ParagraphStyle("dh4", fontSize=9, fontName="Helvetica-Bold",
                                 textColor=WHITE, alignment=TA_CENTER)),
    ]
    det_rows = [det_header]
    col_widths = [content_width * 0.38, content_width * 0.2,
                  content_width * 0.2,  content_width * 0.22]

    for det in detectors:
        dc = _score_color(det["ai_pct"])
        badge = "AI" if det["ai_pct"] >= 70 else "Mixed" if det["ai_pct"] >= 40 else "Human"
        det_rows.append([
            Paragraph(f"{det.get('icon','')} {det['name']}",
                      ParagraphStyle("dn", fontSize=9)),
            Paragraph(f"<font color='#{dc.hexval()[2:]}'><b>{det['ai_pct']:.1f}%</b></font>",
                      ParagraphStyle("da", fontSize=9, alignment=TA_CENTER)),
            Paragraph(f"<font color='#22c55e'><b>{det['human_pct']:.1f}%</b></font>",
                      ParagraphStyle("dhu", fontSize=9, alignment=TA_CENTER)),
            Paragraph(f"<b>{badge}</b>",
                      ParagraphStyle("dv", fontSize=9, alignment=TA_CENTER,
                                     textColor=dc)),
        ])

    det_t = Table(det_rows, colWidths=col_widths)
    row_style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("BOX",      (0, 0), (-1, -1), 0.5, GREY_MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
        ("VALIGN",   (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i in range(1, len(det_rows)):
        if i % 2 == 0:
            row_style.append(("BACKGROUND", (0, i), (-1, i), GREY_LITE))
    det_t.setStyle(TableStyle(row_style))
    story.append(det_t)

    # ── TEXT EXCERPT ───────────────────────────────────────────────────────────
    if text_excerpt:
        story.append(Spacer(1, 5 * mm))
        story.append(_section_title("Analyzed Text (excerpt)"))
        excerpt = text_excerpt[:600] + ("…" if len(text_excerpt) > 600 else "")
        ex = Table([[Paragraph(
            excerpt,
            ParagraphStyle("ex", fontSize=8, textColor=colors.HexColor("#334155"),
                           leading=12),
        )]], colWidths=[content_width])
        ex.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GREY_LITE),
            ("BOX",        (0, 0), (-1, -1), 0.5, GREY_MID),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ]))
        story.append(ex)

    # ── FOOTER ─────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY_MID,
                            spaceBefore=4, spaceAfter=4))
    story.append(Paragraph(
        "This report was generated by Smart Study Guides AI Detection. "
        "Scores are indicative and may vary across detectors. "
        "For submission, always review results manually.",
        ParagraphStyle("foot", fontSize=7, textColor=GREY_MID, alignment=TA_CENTER),
    ))

    doc.build(story)
    return buf.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
#  PLAGIARISM REPORT
# ──────────────────────────────────────────────────────────────────────────────

def build_plagiarism_report(
    similarity: float,
    sources: list,
    words: int,
    text_excerpt: str = "",
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=15 * mm, bottomMargin=20 * mm,
    )

    content_width = PAGE_W - 2 * MARGIN
    story = []
    original = max(0.0, 100.0 - similarity)

    # ── HEADER ─────────────────────────────────────────────────────────────────
    header_data = [[
        Paragraph("<font color='white'><b>Smart Study Guides</b></font>",
                  ParagraphStyle("h1", fontSize=14, fontName="Helvetica-Bold",
                                 textColor=WHITE)),
        Paragraph(
            "<font color='white'><b>Plagiarism Report</b></font>",
            ParagraphStyle("h2", fontSize=14, fontName="Helvetica-Bold",
                           textColor=WHITE, alignment=TA_RIGHT),
        ),
    ]]
    hdr = Table(header_data, colWidths=[content_width / 2, content_width / 2])
    hdr.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 5 * mm))

    now = datetime.now().strftime("%B %d, %Y  %H:%M")
    meta_data = [[
        Paragraph(f"Generated: {now}",
                  ParagraphStyle("m1", fontSize=8, textColor=GREY_MID)),
        Paragraph(f"Words analyzed: {words:,}",
                  ParagraphStyle("m2", fontSize=8, textColor=GREY_MID, alignment=TA_RIGHT)),
    ]]
    mt = Table(meta_data, colWidths=[content_width / 2, content_width / 2])
    mt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(mt)
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY_MID,
                            spaceAfter=6, spaceBefore=4))

    # ── OVERALL SCORES ─────────────────────────────────────────────────────────
    story.append(_section_title("Overall Result"))

    sim_color = _score_color(similarity) if similarity >= 15 else GREEN
    score_data = [[
        Paragraph(
            f"<font color='#22c55e' size='32'><b>{original:.1f}%</b></font><br/>"
            f"<font color='#94a3b8' size='9'>Original Content</font>",
            ParagraphStyle("sc", alignment=TA_CENTER, leading=36),
        ),
        Paragraph(
            f"<font color='#{sim_color.hexval()[2:]}' size='32'><b>{similarity:.1f}%</b></font><br/>"
            f"<font color='#94a3b8' size='9'>Similarity Detected</font>",
            ParagraphStyle("sc2", alignment=TA_CENTER, leading=36),
        ),
    ]]
    sc = Table(score_data, colWidths=[content_width / 2, content_width / 2])
    sc.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GREY_LITE),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("BOX", (0, 0), (-1, -1), 0.5, GREY_MID),
        ("LINEBEFORE", (1, 0), (1, 0), 0.5, GREY_MID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(sc)
    story.append(Spacer(1, 4 * mm))

    if similarity >= 30:
        vtext, vcolor = "🚨  HIGH SIMILARITY — Likely to be flagged for plagiarism", RED
    elif similarity >= 15:
        vtext, vcolor = "⚠️  MODERATE SIMILARITY — Review matched sources carefully", YELLOW
    else:
        vtext, vcolor = "✅  LOW SIMILARITY — Text appears mostly original", GREEN

    vd = Table([[Paragraph(
        f"<font color='#{vcolor.hexval()[2:]}' size='10'><b>{vtext}</b></font>",
        ParagraphStyle("vd", alignment=TA_CENTER),
    )]], colWidths=[content_width])
    vd.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GREY_LITE),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BOX", (0, 0), (-1, -1), 0.5, GREY_MID),
    ]))
    story.append(vd)

    # ── MATCHED SOURCES ────────────────────────────────────────────────────────
    story.append(Spacer(1, 5 * mm))
    story.append(_section_title(f"Matched Sources  ({len(sources)} found)"))

    if sources:
        src_header = [
            Paragraph("<b>#</b>",
                      ParagraphStyle("sh0", fontSize=9, fontName="Helvetica-Bold",
                                     textColor=WHITE, alignment=TA_CENTER)),
            Paragraph("<b>Source</b>",
                      ParagraphStyle("sh1", fontSize=9, fontName="Helvetica-Bold",
                                     textColor=WHITE)),
            Paragraph("<b>Match</b>",
                      ParagraphStyle("sh2", fontSize=9, fontName="Helvetica-Bold",
                                     textColor=WHITE, alignment=TA_CENTER)),
        ]
        src_rows = [src_header]
        col_widths_s = [content_width * 0.07, content_width * 0.78, content_width * 0.15]

        for idx, src in enumerate(sources, 1):
            sc2 = _score_color(src["match_pct"])
            url_text = src.get("url", "")
            if url_text:
                url_display = (url_text[:70] + "…") if len(url_text) > 70 else url_text
                url_para = Paragraph(
                    f"<font size='7' color='#5a8aee'>{url_display}</font>",
                    ParagraphStyle("su", fontSize=7),
                )
            else:
                url_para = Paragraph("", ParagraphStyle("su2"))

            title_short = (src["title"][:90] + "…") if len(src["title"]) > 90 else src["title"]
            src_rows.append([
                Paragraph(str(idx),
                          ParagraphStyle("si", fontSize=9, alignment=TA_CENTER,
                                         textColor=GREY_MID)),
                [
                    Paragraph(title_short,
                              ParagraphStyle("st", fontSize=9,
                                             textColor=BLACK)),
                    url_para,
                ],
                Paragraph(f"<font color='#{sc2.hexval()[2:]}'><b>{src['match_pct']:.1f}%</b></font>",
                          ParagraphStyle("sm", fontSize=10, alignment=TA_CENTER,
                                         fontName="Helvetica-Bold")),
            ])

        src_t = Table(src_rows, colWidths=col_widths_s)
        src_style = [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("BOX",       (0, 0), (-1, -1), 0.5, GREY_MID),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
            ("VALIGN",    (0, 0), (-1, -1), "TOP"),
        ]
        for i in range(1, len(src_rows)):
            if i % 2 == 0:
                src_style.append(("BACKGROUND", (0, i), (-1, i), GREY_LITE))
        src_t.setStyle(TableStyle(src_style))
        story.append(src_t)
    else:
        no_src = Table([[Paragraph(
            "✅  No matching sources found — this text appears to be original.",
            ParagraphStyle("ns", fontSize=10, textColor=GREEN, alignment=TA_CENTER),
        )]], colWidths=[content_width])
        no_src.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GREY_LITE),
            ("TOPPADDING",    (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("BOX", (0, 0), (-1, -1), 0.5, GREY_MID),
        ]))
        story.append(no_src)

    # ── TEXT EXCERPT ───────────────────────────────────────────────────────────
    if text_excerpt:
        story.append(Spacer(1, 5 * mm))
        story.append(_section_title("Analyzed Text (excerpt)"))
        excerpt = text_excerpt[:600] + ("…" if len(text_excerpt) > 600 else "")
        ex = Table([[Paragraph(
            excerpt,
            ParagraphStyle("ex", fontSize=8, textColor=colors.HexColor("#334155"),
                           leading=12),
        )]], colWidths=[content_width])
        ex.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GREY_LITE),
            ("BOX",        (0, 0), (-1, -1), 0.5, GREY_MID),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ]))
        story.append(ex)

    # ── FOOTER ─────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY_MID,
                            spaceBefore=4, spaceAfter=4))
    story.append(Paragraph(
        "This report was generated by Smart Study Guides Plagiarism Checker, powered by Copyleaks. "
        "Results reflect similarity against indexed web pages and academic databases. "
        "Always verify flagged sources before drawing conclusions.",
        ParagraphStyle("foot", fontSize=7, textColor=GREY_MID, alignment=TA_CENTER),
    ))

    doc.build(story)
    return buf.getvalue()
