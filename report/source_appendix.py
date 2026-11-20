"""Embed the annotated input worksheet as a self-contained source snapshot."""

import copy
import hashlib
import io
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl.styles.numbers import BUILTIN_FORMATS, is_datetime
from openpyxl.utils.datetime import CALENDAR_MAC_1904, CALENDAR_WINDOWS_1900

from core.models import UserError
from report.review_overview import SOURCE_SHEET
from report.source_review import CONTENT, DOC_REL, MAIN, _highlight, _rels_path, _target, _xml


def _tag(name):
    return f"{{{MAIN}}}{name}"


def _merge_styles(target, source):
    dst_bytes = target["xl/styles.xml"]
    relations = ET.fromstring(source["xl/_rels/workbook.xml.rels"])
    style_relation = next((n for n in relations if n.get("Type", "").endswith("/styles")), None)
    if style_relation is None:
        from openpyxl import Workbook
        from openpyxl.styles.stylesheet import write_stylesheet

        default = Workbook()
        source_styles = ET.tostring(write_stylesheet(default))
        default.close()
    else:
        source_styles = source[_target("xl/workbook.xml", style_relation.get("Target"))]
    dst, src = ET.fromstring(dst_bytes), ET.fromstring(source_styles)
    themes = []
    if "xl/theme/theme1.xml" in source:
        theme = ET.fromstring(source["xl/theme/theme1.xml"])
        scheme = theme.find(".//{http://schemas.openxmlformats.org/drawingml/2006/main}clrScheme")
        if scheme is not None:
            # Spreadsheet theme order differs from the drawing scheme's order.
            by_name = {
                n.tag.rsplit("}", 1)[-1]: next(iter(n)).get("lastClr", next(iter(n)).get("val"))
                for n in scheme
            }
            themes = [
                by_name.get(n)
                for n in (
                    "lt1",
                    "dk1",
                    "lt2",
                    "dk2",
                    "accent1",
                    "accent2",
                    "accent3",
                    "accent4",
                    "accent5",
                    "accent6",
                    "hlink",
                    "folHlink",
                )
            ]

    def cloned(node):
        node = copy.deepcopy(node)
        for item in node.iter():
            if "theme" in item.attrib and int(item.get("theme")) < len(themes):
                color = themes[int(item.get("theme"))]
                if color:
                    item.attrib.pop("theme")
                    item.set("rgb", "FF" + color[-6:])
        return node

    def section(name):
        node = dst.find(_tag(name))
        if node is None:
            node = ET.Element(_tag(name))
            # Keep the schema sequence for the sections used below.
            order = [
                "numFmts",
                "fonts",
                "fills",
                "borders",
                "cellStyleXfs",
                "cellXfs",
                "cellStyles",
                "dxfs",
                "tableStyles",
                "colors",
                "extLst",
            ]
            index = next(
                (
                    i
                    for i, n in enumerate(dst)
                    if n.tag.rsplit("}", 1)[-1] in order
                    and order.index(n.tag.rsplit("}", 1)[-1]) > order.index(name)
                ),
                len(dst),
            )
            dst.insert(index, node)
        return node

    formats = section("numFmts")
    codes = {n.get("formatCode"): int(n.get("numFmtId")) for n in formats}
    next_id = max([163, *codes.values()]) + 1
    number_map = {}
    for item in src.findall(_tag("numFmts") + "/" + _tag("numFmt")):
        code = item.get("formatCode")
        if code not in codes:
            node = cloned(item)
            node.set("numFmtId", str(next_id))
            formats.append(node)
            codes[code] = next_id
            next_id += 1
        number_map[item.get("numFmtId")] = str(codes[code])
    offsets = {}
    for name in ("fonts", "fills", "borders", "cellStyleXfs", "cellXfs", "dxfs"):
        parent = section(name)
        offsets[name] = len(parent)
        original = src.find(_tag(name))
        if original is None:
            continue
        for item in original:
            node = cloned(item)
            for child in node.iter():
                for attr, collection in (
                    ("fontId", "fonts"),
                    ("fillId", "fills"),
                    ("borderId", "borders"),
                    ("xfId", "cellStyleXfs"),
                ):
                    if attr in child.attrib:
                        child.set(attr, str(int(child.get(attr)) + offsets[collection]))
                if "numFmtId" in child.attrib:
                    child.set(
                        "numFmtId", number_map.get(child.get("numFmtId"), child.get("numFmtId"))
                    )
            parent.append(node)
    for node in dst:
        if node.tag.rsplit("}", 1)[-1] in {"numFmts", *offsets}:
            node.set("count", str(len(node)))
    target["xl/styles.xml"] = _xml(dst, dst_bytes)
    source_formats = {
        n.get("numFmtId"): n.get("formatCode")
        for n in src.findall(_tag("numFmts") + "/" + _tag("numFmt"))
    }
    source_xfs = src.find(_tag("cellXfs"))
    offsets["date_styles"] = {
        index
        for index, xf in enumerate(source_xfs if source_xfs is not None else [])
        if is_datetime(
            source_formats.get(
                xf.get("numFmtId"), BUILTIN_FORMATS.get(int(xf.get("numFmtId", "0")), "General")
            )
        )
        in ("date", "datetime")
    }
    return offsets


def append_source_review(path, result):
    """Keep original coordinates/styles/notes; snapshot source formula results."""
    try:
        raw = result.loaded.path.read_bytes()
    except OSError as exc:
        raise UserError("원본 별첨을 만들 수 없습니다. 입력 파일 경로를 확인하세요.") from exc
    if hashlib.sha256(raw).hexdigest() != result.loaded.file_hash:
        raise UserError("분석 후 원본 파일이 변경되었습니다. 다시 읽고 분석한 뒤 출력하세요.")
    with ZipFile(io.BytesIO(raw)) as archive:
        source = {n: archive.read(n) for n in archive.namelist()}
    _highlight(source, result)
    with ZipFile(path) as archive:
        target = {n: archive.read(n) for n in archive.namelist()}
    book = ET.fromstring(source["xl/workbook.xml"])
    relations = ET.fromstring(source["xl/_rels/workbook.xml.rels"])
    refs = {n.get("Id"): _target("xl/workbook.xml", n.get("Target")) for n in relations}
    sheet_node = next(n for n in book.find(_tag("sheets")) if n.get("name") == result.loaded.sheet)
    source_part = refs[sheet_node.get(f"{{{DOC_REL}}}id")]
    sheet_bytes = source[source_part]
    sheet = ET.fromstring(sheet_bytes)
    offsets = _merge_styles(target, source)

    def epoch(workbook):
        properties = workbook.find(_tag("workbookPr"))
        return (
            CALENDAR_MAC_1904
            if properties is not None and properties.get("date1904") in ("1", "true")
            else CALENDAR_WINDOWS_1900
        )

    date_shift = (epoch(book) - epoch(ET.fromstring(target["xl/workbook.xml"]))).days
    strings = (
        ET.fromstring(source["xl/sharedStrings.xml"]) if "xl/sharedStrings.xml" in source else []
    )
    for node in sheet.iter():
        attr = (
            "s"
            if node.tag in (_tag("c"), _tag("row"))
            else "style"
            if node.tag == _tag("col")
            else None
        )
        if attr and (attr in node.attrib or node.tag == _tag("c")):
            node.set(attr, str(int(node.get(attr, "0")) + offsets["cellXfs"]))
        if "dxfId" in node.attrib:
            node.set("dxfId", str(int(node.get("dxfId")) + offsets["dxfs"]))
    for cell in sheet.iter(_tag("c")):
        formula, value = cell.find(_tag("f")), cell.find(_tag("v"))
        if formula is not None:
            cell.remove(formula)
            # An unavailable cached result is retained as literal formula text,
            # rather than inventing a number or linking to the removed workbook.
            if cell.get("t") == "str" and value is not None:
                cell.remove(value)
                cell.set("t", "inlineStr")
                ET.SubElement(ET.SubElement(cell, _tag("is")), _tag("t")).text = value.text or ""
            elif value is None or value.text is None:
                if value is not None:
                    cell.remove(value)
                cell.set("t", "inlineStr")
                inline = ET.SubElement(cell, _tag("is"))
                ET.SubElement(inline, _tag("t")).text = "=" + (formula.text or "")
        if (
            date_shift
            and cell.get("t", "n") == "n"
            and int(cell.get("s")) - offsets["cellXfs"] in offsets["date_styles"]
            and value is not None
            and value.text
        ):
            value.text = format(float(value.text) + date_shift, ".15g")
        if cell.get("t") == "s":
            value = cell.find(_tag("v"))
            inline = copy.deepcopy(strings[int(value.text)])
            inline.tag = _tag("is")
            cell.remove(value)
            cell.set("t", "inlineStr")
            cell.append(inline)
    from report.appendix_style import apply_raw_styles

    apply_raw_styles(sheet, target, _tag, _merge_styles)
    for view in sheet.findall(_tag("sheetViews") + "/" + _tag("sheetView")):
        view.set("tabSelected", "0")
        view.set("workbookViewId", "0")
        view.set("topLeftCell", "A1")
        for node in list(view):
            if node.tag in (_tag("pane"), _tag("selection")):
                view.remove(node)
        ET.SubElement(view, _tag("selection"), activeCell="A1", sqref="A1")
    properties = sheet.find(_tag("sheetPr"))
    if properties is not None:
        properties.attrib.pop("codeName", None)
    source[source_part] = _xml(sheet, sheet_bytes)
    content = ET.fromstring(target["[Content_Types].xml"])
    source_content = ET.fromstring(source["[Content_Types].xml"])
    overrides = {
        n.get("PartName").lstrip("/"): n.get("ContentType")
        for n in source_content
        if n.get("PartName")
    }
    defaults = {
        n.get("Extension"): n.get("ContentType") for n in source_content if n.get("Extension")
    }
    used = set()
    tables = 100000

    def part_name(name):
        return "xl/source_snapshot/" + name

    def copy_part(name):
        nonlocal tables
        if name in used:
            return
        used.add(name)
        data = source[name]
        if name.startswith("xl/tables/") and name.endswith(".xml"):
            node = ET.fromstring(data)
            tables += 1
            node.set("id", str(tables))
            node.set("name", "SourceSnapshot" + str(tables))
            node.set("displayName", "SourceSnapshot" + str(tables))
            for column in node.iter(_tag("tableColumn")):
                for formula in list(column):
                    if formula.tag in (_tag("calculatedColumnFormula"), _tag("totalsRowFormula")):
                        column.remove(formula)
            data = _xml(node, data)
        target[part_name(name)] = data
        if name in overrides:
            ET.SubElement(
                content,
                f"{{{CONTENT}}}Override",
                PartName="/" + part_name(name),
                ContentType=overrides[name],
            )
        else:
            extension = name.rsplit(".", 1)[-1]
            if extension in defaults and not any(n.get("Extension") == extension for n in content):
                ET.SubElement(
                    content,
                    f"{{{CONTENT}}}Default",
                    Extension=extension,
                    ContentType=defaults[extension],
                )
        rel_path = _rels_path(name)
        if rel_path in source:
            rel_data = source[rel_path]
            rels = ET.fromstring(rel_data)
            for relation in rels:
                if relation.get("TargetMode") == "External":
                    continue
                dependency = _target(name, relation.get("Target"))
                copy_part(dependency)
                relation.set("Target", "/" + part_name(dependency))
            target[_rels_path(part_name(name))] = _xml(rels, rel_data)

    copy_part(source_part)
    dst_book_bytes = target["xl/workbook.xml"]
    dst_book = ET.fromstring(dst_book_bytes)
    dst_rels_bytes = target["xl/_rels/workbook.xml.rels"]
    dst_rels = ET.fromstring(dst_rels_bytes)
    rid = "rIdSourceSnapshot"
    if any(n.get("Id") == rid for n in dst_rels):
        raise UserError("원본 별첨 관계가 이미 존재합니다.")
    ET.SubElement(
        dst_rels,
        dst_rels.tag.replace("Relationships", "Relationship"),
        Id=rid,
        Type=DOC_REL + "/worksheet",
        Target="/" + part_name(source_part),
    )
    sheets = dst_book.find(_tag("sheets"))
    ET.SubElement(
        sheets,
        _tag("sheet"),
        {
            "name": SOURCE_SHEET,
            "sheetId": str(max(int(n.get("sheetId")) for n in sheets) + 1),
            f"{{{DOC_REL}}}id": rid,
        },
    )
    target["xl/workbook.xml"] = _xml(dst_book, dst_book_bytes)
    target["xl/_rels/workbook.xml.rels"] = _xml(dst_rels, dst_rels_bytes)
    target["[Content_Types].xml"] = _xml(content, target["[Content_Types].xml"])
    temporary = path.with_suffix(".source.tmp")
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as output:
            for name, data in target.items():
                output.writestr(name, data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
