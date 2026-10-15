"""Reusable print layout. System fonts are embedded as PDF subsets, not shipped."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from html import escape
import math
import os
import re
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, Table, TableStyle, Flowable
from core.models import UserError

INK = colors.HexColor('#25313B')
MUTED = colors.HexColor('#61707D')
RULE = colors.HexColor('#D7DDE2')
PANEL = colors.HexColor('#F2F4F6')
WHITE = colors.white
PALETTE = [colors.HexColor(h) for h in ('#344552','#657785','#8C9EAC','#B2BDC7','#CFD6DC','#E8EDF0')]


def clean(value: object) -> str:
    """Escape source text before passing it to ReportLab's XML paragraph parser."""
    text = str(value) if value is not None else ''
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    return escape(text).replace('\n', '<br/>')


@dataclass(frozen=True)
class Fonts:
    regular: str
    bold: str


def load_fonts(preferred_path: str = '') -> Fonts:
    """Use an approved installed Korean TTF. Never download or copy font files."""
    candidates: list[tuple[Path, Path]] = []
    if preferred_path:
        path = Path(preferred_path).expanduser()
        candidates.append((path, path))
    windir = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    candidates.extend([(windir/'malgun.ttf', windir/'malgunbd.ttf')])
    from matplotlib import font_manager
    available = font_manager.fontManager.ttflist
    for family in ('KoPubWorldDotum', 'KoPubWorld Dotum', 'KoPubWorldDotum_Pro',
                   'Malgun Gothic', 'NanumGothic', 'NanumBarunGothic', 'UnDotum'):
        matches = [font for font in available if font.name == family and Path(font.fname).suffix.lower() == '.ttf']
        if matches:
            matches.sort(key=lambda font: abs(int(font.weight) - 400) if isinstance(font.weight, int) else 0)
            bold = next((font for font in matches if isinstance(font.weight, int) and font.weight >= 600), matches[0])
            candidates.append((Path(matches[0].fname), Path(bold.fname)))
    candidates.extend([(Path('/usr/share/fonts/truetype/nanum/NanumGothic.ttf'),
                        Path('/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf'))])
    for normal, bold_path in candidates:
        if not normal.is_file():
            continue
        try:
            token = sha256(str(normal.resolve()).encode()).hexdigest()[:10]
            reg, bold = 'EFA_KR_' + token, 'EFA_KR_B_' + token
            if reg not in pdfmetrics.getRegisteredFontNames():
                face = TTFont(reg, str(normal))
                if ord('\ud55c') not in face.face.charToGlyph:
                    continue
                pdfmetrics.registerFont(face)
            if bold not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(bold, str(bold_path if bold_path.is_file() else normal)))
            pdfmetrics.registerFontFamily(reg, normal=reg, bold=bold, italic=reg, boldItalic=bold)
            return Fonts(reg, bold)
        except Exception:
            continue
    raise UserError('\ud55c\uae00 PDF\uc6a9 \uae00\uaf34\ub97c \ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4. Windows\uc758 \ub9d1\uc740 \uace0\ub515 \ub610\ub294 \uc124\uce58\ub41c \ud55c\uae00 TTF\ub97c \ud655\uc778\ud558\uace0 final_report.json\uc758 font_path\ub97c \uc9c0\uc815\ud558\uc138\uc694.')


class Layout:
    def __init__(self, fonts: Fonts, width: float):
        self.fonts, self.width = fonts, width
        base = dict(fontName=fonts.regular, fontSize=9.3, leading=15.5,
                    textColor=INK, wordWrap='CJK', spaceAfter=7)
        self.styles = {'body': ParagraphStyle('body', **base)}
        for key, changes in {
            'title': dict(fontName=fonts.bold, fontSize=23, leading=32, spaceAfter=12, keepWithNext=True),
            'h1': dict(fontName=fonts.bold, fontSize=17, leading=25, spaceAfter=11, keepWithNext=True),
            'h2': dict(fontName=fonts.bold, fontSize=11.5, leading=18, spaceBefore=10, spaceAfter=7, keepWithNext=True),
            'muted': dict(fontSize=8.3, leading=13, textColor=MUTED),
            'small': dict(fontSize=7.7, leading=12, textColor=MUTED),
            'cell': dict(fontSize=8.5, leading=13, spaceAfter=0),
            'head': dict(fontName=fonts.bold, fontSize=8.4, leading=13, spaceAfter=0, textColor=WHITE),
            'eyebrow': dict(fontName=fonts.bold, fontSize=8, leading=12, textColor=MUTED, spaceAfter=7),
            'kpi_label': dict(fontSize=8.5, leading=13, textColor=MUTED, spaceAfter=5),
            'kpi': dict(fontName=fonts.bold, fontSize=22, leading=29, spaceAfter=0),
        }.items():
            self.styles[key] = ParagraphStyle(key, parent=self.styles['body'], **changes)

    def p(self, value: object, style: str = 'body', align: int | None = None) -> Paragraph:
        chosen = self.styles[style]
        if align is not None:
            chosen = ParagraphStyle(style+'_aligned', parent=chosen, alignment=align)
        return Paragraph(clean(value), chosen)

    def heading(self, value: object) -> Paragraph:
        return self.p(value, 'h1')

    def table(self, headers: list[str], rows: list[list], widths: list[float],
              numeric: tuple[int, ...] = ()) -> Table:
        cells = [[self.p(value, 'head', TA_RIGHT if i in numeric else TA_LEFT)
                  for i, value in enumerate(headers)]]
        for row in rows:
            cells.append([self.p(value, 'cell', TA_RIGHT if i in numeric else TA_LEFT)
                          for i, value in enumerate(row)])
        if len(cells) == 1:
            cells.append([self.p('\ud574\ub2f9 \ub370\uc774\ud130 \uc5c6\uc74c', 'cell')] + ['']*(len(headers)-1))
        table = Table(cells, colWidths=widths, repeatRows=1, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),INK), ('ROWBACKGROUNDS',(0,1),(-1,-1),[WHITE,PANEL]),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'), ('LEFTPADDING',(0,0),(-1,-1),8),
            ('RIGHTPADDING',(0,0),(-1,-1),8), ('TOPPADDING',(0,0),(-1,-1),7),
            ('BOTTOMPADDING',(0,0),(-1,-1),7), ('LINEBELOW',(0,-1),(-1,-1),.5,RULE),
        ]))
        table.spaceAfter = 10
        return table

    def callout(self, value: str) -> Table:
        table = Table([[self.p(value, 'body')]], colWidths=[self.width], hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),PANEL),
            ('LINEBEFORE',(0,0),(0,-1),2.5,INK),('LEFTPADDING',(0,0),(-1,-1),12),
            ('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),10),
            ('BOTTOMPADDING',(0,0),(-1,-1),8)]))
        table.spaceBefore = 6; table.spaceAfter = 10
        return table

    def kpis(self, items: list[tuple[str, str]]) -> Table:
        cells = [[self.p(label,'kpi_label'), self.p(value,'kpi')] for label,value in items]
        table = Table([cells], colWidths=[self.width/len(cells)]*len(cells), hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),PANEL),
            ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),11),
            ('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),11),
            ('BOTTOMPADDING',(0,0),(-1,-1),11)]))
        table.spaceBefore=4; table.spaceAfter=14
        return table


class Donut(Flowable):
    """Vector composition chart with no dependence on screenshot resolution."""
    def __init__(self, shares: list[float], total: str, fonts: Fonts, size: float = 169):
        super().__init__(); self.shares=shares; self.total=total; self.fonts=fonts
        self.width=self.height=size

    def draw(self):
        c=self.canv; center=self.width/2; radius=self.width*.46
        if not self.shares:
            c.setFillColor(MUTED); c.setFont(self.fonts.regular,9)
            c.drawCentredString(center,center,'\uc9d1\uacc4\uac12 \uc5c6\uc74c'); return
        angle=90.0
        for idx,share in enumerate(self.shares):
            sweep=share*360; col=PALETTE[idx % len(PALETTE)]
            c.setFillColor(col); c.setStrokeColor(WHITE); c.setLineWidth(1.2)
            c.wedge(center-radius,center-radius,center+radius,center+radius,
                    startAng=angle,extent=-sweep,stroke=1,fill=1)
            if share>=.04:
                theta=math.radians(angle-sweep/2)
                x=center+radius*.815*math.cos(theta); y=center+radius*.815*math.sin(theta)
                c.setFillColor(WHITE if idx % len(PALETTE)<2 else INK)
                c.setFont(self.fonts.bold,8); c.drawCentredString(x,y-2.6,f'{share:.1%}')
            angle-=sweep
        c.setFillColor(WHITE); c.circle(center,center,radius*.60,stroke=0,fill=1)
        c.setFillColor(INK); c.setFont(self.fonts.bold,22); c.drawCentredString(center,center+1,self.total)
        c.setFillColor(MUTED); c.setFont(self.fonts.regular,8)
        c.drawCentredString(center,center-17,'\uc804\uccb4 \uac74\uc218')


class Swatch(Flowable):
    def __init__(self, index: int):
        super().__init__(); self.index=index; self.width=10; self.height=10
    def draw(self):
        self.canv.setFillColor(PALETTE[self.index % len(PALETTE)])
        self.canv.rect(0,0,9,9,stroke=0,fill=1)
