"""
Career document PDF builder using reportlab.
Mirrors the industry-aware styling of career_docx_builder.py.
"""
import io
import re
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black, Color
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    ListFlowable, ListItem, KeepTogether,
)
from reportlab.platypus.flowables import HRFlowable

# ── Reuse industry detection from docx builder ────────────────────────────────
from .career_docx_builder import _detect_industry, _classify, _parse_inline

# ── Industry colour map ───────────────────────────────────────────────────────
_HEADING_COLORS = {
    "corporate":  HexColor("#1F3864"),
    "creative":   HexColor("#5B21B6"),
    "technical":  HexColor("#1E40AF"),
    "hospitality":HexColor("#92400E"),
    "medical":    HexColor("#065F46"),
    "education":  HexColor("#78350F"),
    "general":    HexColor("#1E3A5F"),
}

_DIVIDER_COLORS = {
    "corporate":  HexColor("#BFD3E8"),
    "creative":   HexColor("#DDD6FE"),
    "technical":  HexColor("#BFDBFE"),
    "hospitality":HexColor("#FDE68A"),
    "medical":    HexColor("#A7F3D0"),
    "education":  HexColor("#FED7AA"),
    "general":    HexColor("#BFDBFE"),
}

_FONTS = {
    "corporate":  "Helvetica",
    "creative":   "Helvetica",
    "technical":  "Helvetica",
    "hospitality":"Helvetica",
    "medical":    "Helvetica",
    "education":  "Helvetica",
    "general":    "Helvetica",
}

_DIVIDERS = {
    "technical": False,
}


def _make_styles(industry: str):
    hc   = _HEADING_COLORS.get(industry, HexColor("#1E3A5F"))
    font = _FONTS.get(industry, "Helvetica")
    bold = font + "-Bold"

    title = ParagraphStyle(
        "Title",
        fontName=bold,
        fontSize=18,
        textColor=hc,
        alignment=TA_CENTER,
        spaceAfter=4,
        leading=22,
    )
    contact = ParagraphStyle(
        "Contact",
        fontName=font,
        fontSize=9,
        textColor=HexColor("#64748B"),
        alignment=TA_CENTER,
        spaceAfter=2,
        leading=13,
    )
    heading1 = ParagraphStyle(
        "Heading1",
        fontName=bold,
        fontSize=11,
        textColor=hc,
        spaceBefore=10,
        spaceAfter=3,
        leading=14,
    )
    heading2 = ParagraphStyle(
        "Heading2",
        fontName=bold,
        fontSize=10,
        textColor=hc,
        spaceBefore=6,
        spaceAfter=2,
        leading=13,
    )
    body = ParagraphStyle(
        "Body",
        fontName=font,
        fontSize=10,
        textColor=black,
        leading=15,
        spaceAfter=5,
        alignment=TA_LEFT,
    )
    bullet_style = ParagraphStyle(
        "BulletItem",
        fontName=font,
        fontSize=10,
        textColor=black,
        leading=14,
        leftIndent=12,
        spaceAfter=2,
    )
    return {
        "title":   title,
        "contact": contact,
        "h1":      heading1,
        "h2":      heading2,
        "body":    body,
        "bullet":  bullet_style,
        "hc":      hc,
        "divider": _DIVIDER_COLORS.get(industry, HexColor("#BFDBFE")),
        "use_divider": _DIVIDERS.get(industry, True),
    }


def _inline_markup(text: str) -> str:
    """Convert **bold** markers to reportlab <b> tags."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def build_career_pdf(content: str, doc_label: str, doc_type: str,
                     details: dict) -> bytes:
    position = details.get("position", "")
    industry = _detect_industry(position, doc_label)
    st       = _make_styles(industry)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
        title=doc_label,
        author=details.get("full_name", ""),
    )

    story = []
    lines = content.split("\n")
    n     = len(lines)
    i     = 0

    # ── Phase 1: leading contact / header block ───────────────────────────────
    header_lines = []
    j = 0
    while j < n and j < 12:
        s = lines[j].strip()
        if not s:
            if header_lines:
                break
            j += 1
            continue
        kind, _ = _classify(lines[j])
        if kind in ("h1", "h2") and header_lines:
            break
        header_lines.append(lines[j].rstrip())
        j += 1

    if header_lines:
        first = header_lines[0].strip()
        story.append(Paragraph(first, st["title"]))
        for hl in header_lines[1:]:
            s = hl.strip()
            if s:
                story.append(Paragraph(_inline_markup(s), st["contact"]))
        story.append(Spacer(1, 8))
        i = j
    else:
        i = 0

    # ── Phase 2: render body ──────────────────────────────────────────────────
    blank_count = 0
    while i < n:
        raw  = lines[i]
        kind, text = _classify(raw)
        i += 1

        if kind == "blank":
            blank_count += 1
            if blank_count <= 1:
                story.append(Spacer(1, 5))
            continue

        blank_count = 0
        marked = _inline_markup(text)

        if kind == "h1":
            story.append(Paragraph(marked, st["h1"]))
            if st["use_divider"]:
                story.append(HRFlowable(
                    width="100%", thickness=0.75,
                    color=st["divider"], spaceAfter=4,
                ))
        elif kind == "h2":
            story.append(Paragraph(marked, st["h2"]))
        elif kind == "bullet":
            story.append(Paragraph("• " + marked, st["bullet"]))
        else:
            story.append(Paragraph(marked, st["body"]))

    doc.build(story)
    return buf.getvalue()
