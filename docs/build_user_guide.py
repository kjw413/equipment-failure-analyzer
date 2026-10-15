"""Build the top-level USER_GUIDE.pdf from docs/USER_GUIDE.txt.

Format: '# ' chapter (new page), '## ' section, lines containing ' | ' form a table
(first line = header), other lines are paragraphs.
Usage (from source/): .venv\\Scripts\\python.exe docs\\build_user_guide.py
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, PageBreak
from report.pdf_layout import Layout, load_fonts, MUTED, RULE
from version import VERSION


def build(source: Path, target: Path) -> Path:
    fonts = load_fonts()
    width = A4[0]-88
    layout = Layout(fonts, width)
    story, table = [], []

    def flush():
        if table:
            columns = max(len(row) for row in table)
            rows = [row+['']*(columns-len(row)) for row in table]
            first = min(150, width/columns) if columns > 1 else width
            widths = [first]+[(width-first)/(columns-1)]*(columns-1) if columns > 1 else [width]
            story.append(layout.table(rows[0], rows[1:], widths))
            table.clear()

    for line in source.read_text(encoding='utf-8').splitlines():
        text = line.strip()
        if ' | ' in text:
            table.append([cell.strip() for cell in text.split(' | ')])
            continue
        flush()
        if not text:
            continue
        if text.startswith('# '):
            if story:
                story.append(PageBreak())
            story.append(layout.p(text[2:], 'h1'))
        elif text.startswith('## '):
            story.append(layout.p(text[3:], 'h2'))
        else:
            story.append(layout.p(text))
    flush()

    def decorate(canvas, doc):
        canvas.saveState(); canvas.setStrokeColor(RULE); canvas.setLineWidth(.5)
        canvas.line(44, A4[1]-30, A4[0]-44, A4[1]-30)
        canvas.setFillColor(MUTED); canvas.setFont(fonts.regular, 7.5)
        canvas.drawString(44, A4[1]-22, f'EQUIPMENT FAILURE ANALYZER | USER GUIDE v{VERSION}')
        canvas.drawRightString(A4[0]-44, A4[1]-22, str(doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(str(target), pagesize=A4, rightMargin=44, leftMargin=44, topMargin=48, bottomMargin=46,
                            title=f'EFA v{VERSION} - Installation and User Guide', pageCompression=1)
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return target


if __name__ == '__main__':
    print(build(ROOT/'docs'/'USER_GUIDE.txt', ROOT.parent/'USER_GUIDE.pdf'))
