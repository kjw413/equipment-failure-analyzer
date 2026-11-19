"""Company chart number format, applied without reserializing native chart XML."""

import re
from html import unescape

INTEGER_FORMAT = "#,##0"
_PREFIX = r"(?:[A-Za-z_][\w.-]*:)?"


def _numeric(code):
    code = unescape(code)
    if code == "General":
        return True
    tokens = re.sub(r'"[^"]*"|\\.', "", code)
    return "%" not in tokens and not re.search(r"[ymdhs]", tokens, re.IGNORECASE)


def format_chart_numbers(raw: bytes) -> bytes:
    """Format integer values explicitly, retaining percent/date formats and XML design."""
    text = raw.decode("utf-8")

    def existing(match):
        tag = match[0]
        code = re.search(r'\bformatCode="([^"]*)"', tag)
        if code is None or not _numeric(code[1]):
            return tag
        tag = tag[: code.start(1)] + INTEGER_FORMAT + tag[code.end(1) :]
        if re.search(r'\bsourceLinked="[^"]*"', tag):
            return re.sub(r'\bsourceLinked="[^"]*"', 'sourceLinked="0"', tag)
        return tag.replace("/>", ' sourceLinked="0"/>')

    text = re.sub(rf"<{_PREFIX}numFmt\b[^>]*/>", existing, text)

    def cache(match):
        return match[1] + (INTEGER_FORMAT if _numeric(match[2]) else match[2]) + match[3]

    text = re.sub(rf"(<{_PREFIX}formatCode>)([^<]*)(</{_PREFIX}formatCode>)", cache, text)

    def container(match):
        prefix, kind, inner = match["prefix"], match["kind"], match["inner"]
        direct = re.sub(rf"<{prefix}dLbl\b[^>]*>.*?</{prefix}dLbl>", "", inner, flags=re.DOTALL)
        if re.search(rf"<{prefix}numFmt\b", direct):
            return match[0]
        if re.search(rf'<{prefix}showPercent\b[^>]*val="1"', direct) and not re.search(
            rf'<{prefix}showVal\b[^>]*val="1"', direct
        ):
            return match[0]
        # OOXML requires numFmt after title/gridlines (axes), tx (one label),
        # or delete/the repeated dLbl children (a label collection).
        preceding = {
            "valAx": ("title", "minorGridlines", "majorGridlines", "axPos"),
            "dLbl": ("tx", "layout", "delete", "idx"),
            "dLbls": ("delete", "dLbl"),
        }[kind]
        position = 0
        for name in preceding:
            nodes = list(
                re.finditer(
                    rf"<{prefix}{name}\b[^>]*(?:/>|>.*?</{prefix}{name}>)",
                    inner,
                    flags=re.DOTALL,
                )
            )
            if nodes:
                position = nodes[-1].end()
                break
        fmt = f'<{prefix}numFmt formatCode="{INTEGER_FORMAT}" sourceLinked="0"/>'
        return match["start"] + inner[:position] + fmt + inner[position:] + match["end"]

    # Handle individual overrides before their enclosing label collections.
    for kind in ("dLbl", "dLbls", "valAx"):
        pattern = (
            rf"(?P<start><(?P<prefix>{_PREFIX})(?P<kind>{kind})\b[^>]*>)"
            rf"(?P<inner>.*?)(?P<end></(?P=prefix){kind}>)"
        )
        text = re.sub(pattern, container, text, flags=re.DOTALL)
    return text.encode("utf-8")
