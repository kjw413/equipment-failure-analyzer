"""Extract a data-free, XML-preserving report design from an approved XLSX.

This maintenance command never opens and saves the source through a workbook
library: Excel-specific chart extensions, anchors, styles and sheet formatting
remain intact. Runtime report generation supplies every removed data value.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import struct
import zlib
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CELL = re.compile(r"<c\b(?P<attrs>[^>]*?)(?:/\s*>|>(?P<body>.*?)</c>)", re.S)
SHEET_NAMES = ("01.종합현황", "02.팀별 주요이슈", "03.팀간 비교", "04.월별 주요이슈")

# Only these known generic headings survive. An allowlist prevents an unexpected
# source cell, new source row or stale formula cache from leaking into a release.
STATIC_CELLS = {
    1: {"A1", "A8", "B9", "D9", "A21", "B22", "D22"},
    2: {
        "A1",
        "A4",
        "A5",
        "C5",
        "F5",
        "J5",
        "A7",
        "B8",
        "D8",
        "F8",
        "H8",
        "A10",
        "B10",
        "D10",
        "E10",
        "F10",
        "G10",
        "H10",
        "J10",
        "K10",
        "L10",
    },
    3: {
        "A1",
        "A4",
        "A5",
        "D5",
        "H5",
        "A7",
        "B7",
        "C7",
        "D7",
        "E7",
        "F7",
        "G7",
        "H7",
        "I7",
        "J7",
    },
    4: {
        "A1",
        "A4",
        "A5",
        "C5",
        "E5",
        "I5",
        "I6",
        "A8",
        "B8",
        "C8",
        "D8",
        "E8",
        "F8",
        "G8",
        "H8",
        "I8",
        "J8",
        "K8",
    },
}


# Final positions in the user's edited full-table template.
STATIC_CELLS[2] = {
    "A1",
    "A4",
    "A5",
    "C5",
    "F5",
    "J5",
    "J6",
    "A8",
    "B9",
    "D9",
    "F9",
    "H9",
    "A11",
    "A26",
    "G26",
    "A27",
    "B27",
    "D27",
    "E27",
    "F27",
    "G27",
    "H27",
    "J27",
    "K27",
    "L27",
}
STATIC_CELLS[3] = {"A1", "A4", "A5", "D5", "H5", *(f"{c}20" for c in "ABCDEFGHIJ")}
STATIC_CELLS[4] = {"A1", "A4", "A5", "C5", "E5", "I5", "I6", *(f"{c}21" for c in "ABCDEFGHIJK")}


def png_chunk(kind: bytes, value: bytes) -> bytes:
    return (
        struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value))
    )


BLANK_PNG = (
    b"\x89PNG\r\n\x1a\n"
    + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    + png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
    + png_chunk(b"IEND", b"")
)


def relationship_path(part: str) -> str:
    parent, name = posixpath.split(part)
    return posixpath.join(parent, "_rels", name + ".rels")


def resolved_target(part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(part), target))


def clean_sheet(xml: str, index: int, shared_strings: list[str]) -> str:
    def replace_cell(match: re.Match[str]) -> str:
        attrs = match.group("attrs").rstrip()
        address = re.search(r'\br="([A-Z]+[0-9]+)"', attrs)
        body = match.group("body") or ""
        if address is None:
            raise ValueError("Worksheet cell has no address")
        if address.group(1) not in STATIC_CELLS[index] or "<f" in body:
            attrs = re.sub(r'\s+t="[^"]*"', "", attrs)
            return f"<c{attrs}/>"
        if re.search(r'\bt="s"', attrs):
            value = re.search(r"<v>([0-9]+)</v>", body)
            if value is None:
                raise ValueError("Shared-string cell has no index")
            attrs = re.sub(r'\s+t="s"', ' t="inlineStr"', attrs)
            return f"<c{attrs}><is>{shared_strings[int(value.group(1))]}</is></c>"
        if re.search(r'\bt="(?:inlineStr|str)"', attrs):
            return match.group(0)
        # Headings must be text. A changed template must not accidentally leave
        # numeric data in a formerly static coordinate.
        attrs = re.sub(r'\s+t="[^"]*"', "", attrs)
        return f"<c{attrs}/>"

    section = re.search(r"<sheetData>.*?</sheetData>", xml, re.S)
    if section is None:
        raise ValueError("Worksheet has no sheetData")
    xml = xml[: section.start()] + CELL.sub(replace_cell, section.group(0)) + xml[section.end() :]
    # Printer device settings can contain local printer/account names. The
    # independent paper size, orientation, scaling and margins remain untouched.
    xml = re.sub(
        r"<pageSetup\b[^>]*/>",
        lambda match: re.sub(r'\s+r:id="[^"]*"', "", match.group(0)),
        xml,
    )
    return xml


def clean_chart(xml: str) -> str:
    xml = xml.replace("04.고장추이", SHEET_NAMES[3])
    # Delete cached point values, preserving native chart references, number
    # formats, layout, series formatting and all Excel extension namespaces.
    xml = re.sub(r"<c:(strCache|numCache)\b[^>]*>.*?</c:\1>", "", xml, flags=re.S)
    if "#REF!" in xml:
        # Moving the edited table left Excel's optional series-name extension
        # pointing to a deleted cell. Bind it to the numeric column's header.
        value = re.search(r"<c:numRef><c:f>(.*?)!\$([A-Z]+)\$(\d+):", xml)
        if value is None:
            raise ValueError("Cannot repair the moved chart's missing series header")
        header = f"{value[1]}!${value[2]}${int(value[3]) - 1}"
        xml = re.sub(
            r"<c:strRef>(?:(?!</c:strRef>).)*#REF!(?:(?!</c:strRef>).)*</c:strRef>",
            lambda _: f"<c:strRef><c:f>{header}</c:f></c:strRef>",
            xml,
            flags=re.S,
        )
    if "#REF!" in xml:
        raise ValueError("A chart still contains a broken reference")
    return xml


def clean_workbook(xml: str) -> str:
    xml = xml.replace("04.고장추이", SHEET_NAMES[3])
    root = ET.fromstring(xml)
    sheets = root.find(f"{{{MAIN}}}sheets")
    if sheets is None or tuple(sheet.get("name") for sheet in list(sheets)[:4]) != SHEET_NAMES:
        raise ValueError("The first four sheet names do not match the approved template")
    xml = re.sub(
        r"<sheets>.*?</sheets>",
        lambda _: "<sheets>" + "".join(re.findall(r"<sheet\b[^>]*/>", xml)[:4]) + "</sheets>",
        xml,
        flags=re.S,
    )

    def retain_name(match: re.Match[str]) -> str:
        text = match.group(0)
        name = re.search(r'\bname="([^"]+)"', text)
        local = re.search(r'\blocalSheetId="([0-9]+)"', text)
        if local and int(local.group(1)) >= 4:
            return ""
        if name and name.group(1).startswith("_Issue_"):
            return re.sub(
                r">.*?</definedName>", ">'01.종합현황'!$A$3</definedName>", text, flags=re.S
            )
        return text if local and int(local.group(1)) < 4 else ""

    xml = re.sub(r"<definedName\b[^>]*>.*?</definedName>", retain_name, xml, flags=re.S)
    xml = re.sub(r"<mc:AlternateContent\b.*?</mc:AlternateContent>", "", xml, flags=re.S)
    xml = re.sub(r"<xr:revisionPtr\b[^>]*/>", "", xml)
    xml = re.sub(r'\bactiveTab="[0-9]+"', 'activeTab="0"', xml)
    return xml


def build_template(source: Path, destination: Path) -> dict:
    if source.resolve() == destination.resolve():
        raise ValueError("Source and destination must be different files")
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    with ZipFile(source) as archive:
        shared_xml = archive.read("xl/sharedStrings.xml").decode("utf-8")
        shared = re.findall(r"<si\b[^>]*>(.*?)</si>", shared_xml, re.S)
        payload: dict[str, bytes] = {}

        def copy_part(part: str) -> None:
            if part in payload:
                return
            raw = archive.read(part)
            if re.fullmatch(r"xl/worksheets/sheet[1-4]\.xml", part):
                index = int(re.search(r"sheet([1-4])", part).group(1))
                raw = clean_sheet(raw.decode("utf-8"), index, shared).encode("utf-8")
            elif part.startswith("xl/charts/") and part.endswith(".xml"):
                raw = clean_chart(raw.decode("utf-8")).encode("utf-8")
            elif part.startswith("xl/media/"):
                raw = BLANK_PNG
            payload[part] = raw
            rel_path = relationship_path(part)
            if rel_path not in archive.namelist():
                return
            rel_xml = archive.read(rel_path).decode("utf-8")

            def retain_relationship(match: re.Match[str]) -> str:
                relation = ET.fromstring(match.group(0))
                if relation.get("TargetMode") == "External":
                    return ""
                target = resolved_target(part, relation.attrib["Target"])
                if target.startswith("xl/printerSettings/"):
                    return ""
                if not target.startswith(("xl/drawings/", "xl/charts/", "xl/media/")):
                    raise ValueError(f"Unexpected linked template part: {target}")
                copy_part(target)
                return match.group(0)

            payload[rel_path] = re.sub(
                r"<Relationship\b[^>]*/>",
                retain_relationship,
                rel_xml,
            ).encode("utf-8")

        for index in range(1, 5):
            copy_part(f"xl/worksheets/sheet{index}.xml")
        for part in ("xl/styles.xml", "xl/theme/theme1.xml"):
            payload[part] = archive.read(part)
        payload["xl/workbook.xml"] = clean_workbook(
            archive.read("xl/workbook.xml").decode("utf-8")
        ).encode("utf-8")

        workbook_rels = archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
        payload["xl/_rels/workbook.xml.rels"] = re.sub(
            r"<Relationship\b[^>]*/>",
            lambda match: (
                match.group(0)
                if resolved_target(
                    "xl/workbook.xml", ET.fromstring(match.group(0)).attrib["Target"]
                )
                in payload
                else ""
            ),
            workbook_rels,
        ).encode("utf-8")
        payload["docProps/core.xml"] = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator/></cp:coreProperties>'
        ).encode("utf-8")
        payload["docProps/app.xml"] = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            "<Application>Equipment Failure Analyzer</Application></Properties>"
        ).encode("utf-8")
        payload["_rels/.rels"] = archive.read("_rels/.rels")
        content_types = archive.read("[Content_Types].xml").decode("utf-8")
        content_types = re.sub(
            r"<Override\b[^>]*/>",
            lambda match: (
                match.group(0)
                if ET.fromstring(match.group(0)).attrib["PartName"].lstrip("/") in payload
                else ""
            ),
            content_types,
        )
        content_types = re.sub(r'<Default\b[^>]*Extension="bin"[^>]*/>', "", content_types)
        payload["[Content_Types].xml"] = content_types.encode("utf-8")
        payload["[Content_Types].xml"] = payload["[Content_Types].xml"].replace(
            b"application/vnd.ms-excel.sheet.macroEnabled.main+xml",
            b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        )

    # Validate that the package is entirely XML/blank images, has no source
    # caches or formulas and contains only the intended worksheet parts.
    for part, raw in payload.items():
        if part.endswith((".xml", ".rels")):
            try:
                ET.fromstring(raw)
            except ET.ParseError as exc:
                raise ValueError(f"Invalid XML in sanitized part {part}: {exc}") from exc
        if part.startswith("xl/worksheets/") and part.endswith(".xml"):
            assert b"<f>" not in raw and b't="s"' not in raw
        if part.startswith("xl/charts/"):
            assert b"<c:strCache" not in raw and b"<c:numCache" not in raw
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for name, raw in sorted(payload.items()):
            archive.writestr(name, raw)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    return {
        "source_sha256": original_hash,
        "output_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "output_bytes": destination.stat().st_size,
        "retained_parts": sorted(payload),
        "worksheets": list(SHEET_NAMES),
        "native_charts": sum(name.startswith("xl/charts/chart") for name in payload),
        "blank_images": sum(name.startswith("xl/media/") for name in payload),
    }


def build_appendix_layout(source: Path, destination: Path) -> None:
    """Extract only formatting metadata; retain no record values or source formulas."""
    ns = {"s": MAIN}
    layouts = {}
    with ZipFile(source) as archive:
        root = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = {
            e.get("Id"): resolved_target("xl/workbook.xml", e.get("Target"))
            for e in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        areas = {
            int(e.get("localSheetId")): e.text
            for e in root.findall("s:definedNames/s:definedName", ns)
            if e.get("name") == "_xlnm.Print_Area"
        }
        for index, sheet in enumerate(root.findall("s:sheets/s:sheet", ns)):
            if not sheet.get("name", "").startswith("별첨."):
                continue
            part = rels[sheet.get("{" + OFFICE_REL + "}id")]
            xml = ET.fromstring(archive.read(part))
            rows = xml.findall("s:sheetData/s:row", ns)
            heights = Counter(float(e.get("ht", "22")) for e in rows if int(e.get("r")) >= 7)
            bounds = re.findall(r"\$([A-Z]+)\$\d+", areas[index])
            layouts[sheet.get("name")] = {
                "columns": [dict(e.attrib) for e in xml.findall("s:cols/s:col", ns)],
                "row_heights": {
                    e.get("r"): float(e.get("ht", "22")) for e in rows if int(e.get("r")) <= 6
                },
                "body_height": heights.most_common(1)[0][0] if heights else 22,
                "header_styles": {
                    e.get("r"): int(e.get("s", "0"))
                    for row in rows
                    if int(row.get("r")) <= 6
                    for e in row
                },
                "margins": dict(xml.find("s:pageMargins", ns).attrib),
                "page_setup": dict(xml.find("s:pageSetup", ns).attrib),
                "print_columns": [bounds[0], bounds[-1]],
            }
    destination.write_text(json.dumps(layouts, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_template(args.input, args.output), ensure_ascii=False, indent=2))
    build_appendix_layout(args.input, args.output.with_name("report_appendix_layout.json"))


if __name__ == "__main__":
    main()
