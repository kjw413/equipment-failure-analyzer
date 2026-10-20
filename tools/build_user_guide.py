"""Build the top-level USER_GUIDE.pdf from the current rule-based user guide.

Format: '# ' chapter (new page), '## ' section, '### ' sub-section, '- ' bullet,
'> ' highlighted note. Consecutive lines containing ' | ' form a table (first line =
header); a single such line is printed as a paragraph. Other lines are paragraphs.
Usage (from the project folder): .venv/Scripts/python.exe tools/build_user_guide.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import PageBreak, SimpleDocTemplate, Table, TableStyle

from report.pdf_layout import INK, MUTED, PANEL, RULE, WHITE, Layout, load_fonts
from version import VERSION


def word_wrap(layout: Layout) -> None:
    """Break lines between words (어절), as Korean documents do; keep a '_cjk' variant of every
    style for text that has a word too long for its line, such as a folder path."""
    for name, style in list(layout.styles.items()):
        style.wordWrap = None
        layout.styles[name + "_cjk"] = ParagraphStyle(name + "_cjk", parent=style, wordWrap="CJK")


def needs_cjk(text: str, style: ParagraphStyle, width: float) -> bool:
    return any(
        stringWidth(word, style.fontName, style.fontSize) > width for word in str(text).split()
    )


def text_units(value: str) -> int:
    # Hangul and other wide characters take about twice the width of Latin letters.
    return sum(2 if ord(ch) > 0x1100 else 1 for ch in value)


def column_widths(rows: list[list[str]], width: float) -> list[float]:
    """Share the page width by how long each column's text is, so short columns stay narrow."""
    if rows[0] == ["상태", "뜻", "집계"]:
        # Keep six-character status names on one line, including 복수유형확정.
        return [width * 0.16, width * 0.43, width * 0.41]
    columns = len(rows[0])
    weights = [min(max(text_units(row[i]) for row in rows), 60) + 8 for i in range(columns)]
    return [width * weight / sum(weights) for weight in weights]


def build(source: Path, target: Path) -> Path:
    fonts = load_fonts()
    width = A4[0] - 88
    layout = Layout(fonts, width)
    layout.styles["h3"] = ParagraphStyle(
        "h3",
        parent=layout.styles["body"],
        fontName=fonts.bold,
        fontSize=10,
        leading=15,
        spaceBefore=6,
        spaceAfter=4,
        keepWithNext=True,
    )
    layout.styles["bullet"] = ParagraphStyle(
        "bullet", parent=layout.styles["body"], leftIndent=12, firstLineIndent=-9, spaceAfter=4
    )
    word_wrap(layout)
    story, table = [], []

    def para(value: str, style: str = "body", room: float = width, align: int | None = None):
        chosen = style + "_cjk" if needs_cjk(value, layout.styles[style], room) else style
        return layout.p(value, chosen, align)

    def grid(rows: list[list[str]]) -> Table:
        # Same look as Layout.table; each cell picks word or character wrapping for its column width.
        widths = column_widths(rows, width)
        cells = [
            [
                para(value, "head" if r == 0 else "cell", widths[c] - 16, TA_LEFT)
                for c, value in enumerate(row)
            ]
            for r, row in enumerate(rows)
        ]
        result = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
        result.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), INK),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PANEL]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("LINEBELOW", (0, -1), (-1, -1), 0.5, RULE),
                ]
            )
        )
        result.spaceAfter = 10
        return result

    def flush():
        if len(table) == 1:
            story.append(para(" | ".join(table[0])))
        elif table:
            columns = max(len(row) for row in table)
            story.append(grid([row + [""] * (columns - len(row)) for row in table]))
        table.clear()

    for line in source.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if " | " in text:
            table.append([cell.strip() for cell in text.split(" | ")])
            continue
        flush()
        if not text:
            continue
        if text.startswith("# "):
            if story:
                story.append(PageBreak())
            story.append(para(text[2:], "h1"))
        elif text.startswith("## "):
            story.append(para(text[3:], "h2"))
        elif text.startswith("### "):
            story.append(para(text[4:], "h3"))
        elif text.startswith("- "):
            story.append(para("• " + text[2:], "bullet"))
        elif text.startswith("> "):
            story.append(layout.callout(text[2:]))
        else:
            story.append(para(text))
    flush()

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(44, A4[1] - 30, A4[0] - 44, A4[1] - 30)
        canvas.setFillColor(MUTED)
        canvas.setFont(fonts.regular, 7.5)
        canvas.drawString(44, A4[1] - 22, f"EQUIPMENT FAILURE ANALYZER | USER GUIDE v{VERSION}")
        canvas.drawRightString(A4[0] - 44, A4[1] - 22, str(doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        rightMargin=44,
        leftMargin=44,
        topMargin=48,
        bottomMargin=46,
        title=f"EFA v{VERSION} - User Guide and How It Works",
        pageCompression=1,
    )
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return target


if __name__ == "__main__":
    print(build(ROOT / "docs" / "USER_GUIDE.txt", ROOT / "USER_GUIDE.pdf"))
