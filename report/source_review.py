"""Highlight a copy of the source workbook without round-tripping its Excel parts."""

from __future__ import annotations

import copy
import hashlib
import io
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from xml.sax.saxutils import quoteattr

from openpyxl import Workbook
from openpyxl.comments.shape_writer import ShapeWriter
from openpyxl.styles.stylesheet import write_stylesheet
from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter, range_boundaries
from openpyxl.xml.functions import tostring

from core.models import AnalysisResult, Progress, UserError, noop_progress
from core.preprocessing import review_target
from core.review_colors import REVIEW_TYPES, normalized_review_colors, review_types

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT = "http://schemas.openxmlformats.org/package/2006/content-types"
VML = "urn:schemas-microsoft-com:vml"
REVIEW_LAST_COLUMN = 24  # A:X, including empty cells within the requested range.


def _tag(name: str) -> str:
    return f"{{{MAIN}}}{name}"


def _xml(root: ET.Element, original: bytes | None = None) -> bytes:
    """Keep declared prefixes, including prefixes used only by mc:Ignorable."""
    if original:
        namespaces = dict(
            item for _event, item in ET.iterparse(io.BytesIO(original), events=("start-ns",))
        )
    else:
        namespaces = {"": root.tag[1:].split("}", 1)[0]} if root.tag.startswith("{") else {}
    for prefix, uri in namespaces.items():
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass
    output = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    declarations = []
    for prefix, uri in namespaces.items():
        name = "xmlns" + (":" + prefix if prefix else "")
        if (" " + name + "=").encode() not in output:
            declarations.append(f" {name}={quoteattr(uri)}")
    if declarations:
        start = output.index(b"?>") + 2
        start = output.index(b"<", start)
        end = output.index(b">", start)
        insertion = end - 1 if output[end - 1 : end] == b"/" else end
        output = output[:insertion] + "".join(declarations).encode() + output[insertion:]
    return output


def _target(part: str, target: str) -> str:
    return (
        target.lstrip("/")
        if target.startswith("/")
        else posixpath.normpath(posixpath.join(posixpath.dirname(part), target))
    )


def _rels_path(part: str) -> str:
    return posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")


def _new_part(parts: dict[str, bytes], directory: str, stem: str, extension: str) -> str:
    for index in range(1, len(parts) + 2):
        name = f"{directory}/{stem}{index}.{extension}"
        if name not in parts:
            return name
    raise ValueError("Unable to allocate workbook part")


def _add_relation(root, kind, target):
    used = {item.get("Id") for item in root}
    index = 1
    while f"rId{index}" in used:
        index += 1
    rid = f"rId{index}"
    ET.SubElement(
        root, f"{{{PKG_REL}}}Relationship", Id=rid, Type=DOC_REL + "/" + kind, Target=target
    )
    return rid


def _add_comments(parts: dict[str, bytes], sheet_part: str, sheet, notes: dict[str, str]):
    """Append review notes while preserving existing comments and VML objects."""
    rel_path = _rels_path(sheet_part)
    rel_bytes = parts.get(rel_path)
    rels = ET.fromstring(rel_bytes) if rel_bytes else ET.Element(f"{{{PKG_REL}}}Relationships")
    comments_rel = next((rel for rel in rels if rel.get("Type", "").endswith("/comments")), None)
    content = ET.fromstring(parts["[Content_Types].xml"])
    if comments_rel is None:
        comment_part = _new_part(parts, "xl/comments", "review", "xml")
        _add_relation(rels, "comments", "/" + comment_part)
        comments = ET.Element(_tag("comments"))
        ET.SubElement(comments, _tag("authors"))
        ET.SubElement(comments, _tag("commentList"))
        ET.SubElement(
            content,
            f"{{{CONTENT}}}Override",
            PartName="/" + comment_part,
            ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml",
        )
        comment_bytes = None
    else:
        comment_part = _target(sheet_part, comments_rel.get("Target"))
        comment_bytes = parts[comment_part]
        comments = ET.fromstring(comment_bytes)
    authors = comments.find(_tag("authors"))
    author_names = [item.text for item in authors]
    author = "설비 고장 분석기"
    if author not in author_names:
        ET.SubElement(authors, _tag("author")).text = author
        author_names.append(author)
    author_id = str(author_names.index(author))
    comment_list = comments.find(_tag("commentList"))
    existing = {item.get("ref"): item for item in comment_list}
    new_refs = []
    for ref, note in notes.items():
        comment = existing.get(ref)
        if comment is None:
            comment = ET.SubElement(comment_list, _tag("comment"), ref=ref, authorId=author_id)
            text_node = ET.SubElement(comment, _tag("text"))
            new_refs.append(ref)
        else:
            text_node = comment.find(_tag("text"))
            note = "\n\n" + note
            # Rich comment text is a run sequence; avoid mixing a plain <t> with <r>.
            for index, child in enumerate(list(text_node)):
                if child.tag == _tag("t"):
                    text_node.remove(child)
                    original_run = ET.Element(_tag("r"))
                    original_run.append(child)
                    text_node.insert(index, original_run)
        run = ET.SubElement(text_node, _tag("r"))
        ET.SubElement(
            run, _tag("t"), {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}
        ).text = note
    parts[comment_part] = _xml(comments, comment_bytes)
    if new_refs:
        legacy = sheet.find(_tag("legacyDrawing"))
        legacy_id = legacy.get(f"{{{DOC_REL}}}id") if legacy is not None else None
        vml_rel = next((rel for rel in rels if rel.get("Id") == legacy_id), None)
        if vml_rel is None:
            vml_part = _new_part(parts, "xl/drawings", "reviewNotes", "vml")
            rid = _add_relation(rels, "vmlDrawing", "/" + vml_part)
            legacy = ET.Element(_tag("legacyDrawing"), {f"{{{DOC_REL}}}id": rid})
            # legacyDrawing precedes the following optional worksheet elements.
            later = {
                _tag(name)
                for name in (
                    "legacyDrawingHF",
                    "picture",
                    "oleObjects",
                    "controls",
                    "webPublishItems",
                    "tableParts",
                    "extLst",
                )
            }
            index = next((i for i, child in enumerate(sheet) if child.tag in later), len(sheet))
            sheet.insert(index, legacy)
            vml_bytes = None
            vml_root = ET.Element("xml")
        else:
            vml_part = _target(sheet_part, vml_rel.get("Target"))
            vml_bytes = parts[vml_part]
            vml_root = ET.fromstring(vml_bytes)
        writer = ShapeWriter([])
        if vml_root.find(f"{{{VML}}}shapetype[@id='_x0000_t202']") is None:
            writer.add_comment_shapetype(vml_root)
        ids = [
            int(match.group(1))
            for node in vml_root.iter()
            if (match := re.fullmatch(r"_x0000_s(\d+)", node.get("id", "")))
        ]
        for index, ref in enumerate(new_refs, max(ids, default=1025) + 1):
            writer.add_comment_shape(vml_root, index, ref, 160, 400)
        parts[vml_part] = _xml(vml_root, vml_bytes)
        if not any(item.get("Extension") == "vml" for item in content):
            ET.SubElement(
                content,
                f"{{{CONTENT}}}Default",
                Extension="vml",
                ContentType="application/vnd.openxmlformats-officedocument.vmlDrawing",
            )
    parts[rel_path] = _xml(rels, rel_bytes)
    parts["[Content_Types].xml"] = _xml(content, parts["[Content_Types].xml"])


def _review_styles(parts, relations):
    """Styles are optional in OOXML; add defaults only when highlights need them."""
    relation = next((item for item in relations if item.get("Type", "").endswith("/styles")), None)
    default_book = Workbook()
    defaults = ET.fromstring(tostring(write_stylesheet(default_book)))
    default_book.close()
    if relation is None:
        # Canonical name also supports readers that hardcode xl/styles.xml.
        part = "xl/styles.xml"
        _add_relation(relations, "styles", "/" + part)
        rel_part = "xl/_rels/workbook.xml.rels"
        parts[rel_part] = _xml(relations, parts[rel_part])
        content_part = "[Content_Types].xml"
        content = ET.fromstring(parts[content_part])
        ET.SubElement(
            content,
            f"{{{CONTENT}}}Override",
            PartName="/" + part,
            ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml",
        )
        parts[content_part] = _xml(content, parts[content_part])
        if part not in parts:
            return part, None, defaults
    else:
        part = _target("xl/workbook.xml", relation.get("Target"))
    original = parts[part]
    styles = ET.fromstring(original)
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
    positions = {_tag(name): index for index, name in enumerate(order)}
    for name in ("fonts", "fills", "borders", "cellStyleXfs", "cellXfs"):
        section = styles.find(_tag(name))
        if section is not None and len(section):
            continue
        if section is not None:
            styles.remove(section)
        index = next(
            (
                i
                for i, item in enumerate(styles)
                if positions.get(item.tag, len(order)) > positions[_tag(name)]
            ),
            len(styles),
        )
        styles.insert(index, copy.deepcopy(defaults.find(_tag(name))))
    return part, original, styles


def _highlight(parts: dict[str, bytes], result: AnalysisResult):
    if result.tables["review"].empty:
        return
    book = ET.fromstring(parts["xl/workbook.xml"])
    relations = ET.fromstring(parts["xl/_rels/workbook.xml.rels"])
    targets = {item.get("Id"): _target("xl/workbook.xml", item.get("Target")) for item in relations}
    sheet_node = next(
        (item for item in book.find(_tag("sheets")) if item.get("name") == result.loaded.sheet),
        None,
    )
    if sheet_node is None:
        raise UserError("원본 시트를 찾을 수 없습니다. 원본을 다시 읽고 분석하세요.")
    sheet_part = targets[sheet_node.get(f"{{{DOC_REL}}}id")]
    sheet_bytes = parts[sheet_part]
    sheet = ET.fromstring(sheet_bytes)
    style_part = style_bytes = styles = fills = formats = None
    style_cache, fill_cache = {}, {}
    settings = result.config_snapshot.get("settings", {})
    colors = normalized_review_colors(settings.get("review_colors"))
    labels = {key: label for key, label, _color in REVIEW_TYPES}
    columns = {
        field: result.loaded.headers.index(header) + 1
        for field, header in result.loaded.mapping.items()
        if header in result.loaded.headers
    }
    fallback = columns.get("description", 1)
    merges = [range_boundaries(item.get("ref")) for item in sheet.iter(_tag("mergeCell"))]
    sheet_data = sheet.find(_tag("sheetData"))
    rows = {int(item.get("r")): item for item in sheet_data}
    notes = {}

    def safe_column(row_num, column):
        for left, top, right, bottom in merges:
            if left <= column <= right and top <= row_num <= bottom:
                # A vertical merged cell is shared by records and cannot safely carry one row's mark.
                return left if top == bottom else None
        return column

    review = result.tables["review"]
    for record in review.to_dict("records"):
        row_num = int(record["source_row"])
        types = review_types(record, target_review=review_target(settings, result.options)) or (
            "other",
        )
        key = types[0]
        marks = {
            column: key
            for column in range(1, REVIEW_LAST_COLUMN + 1)
            if safe_column(row_num, column) is not None
        }
        if not marks:
            continue
        if styles is None:
            style_part, style_bytes, styles = _review_styles(parts, relations)
            fills, formats = styles.find(_tag("fills")), styles.find(_tag("cellXfs"))
        row = rows.get(row_num)
        if row is None:
            # Merged values can produce source records without a physical XML row.
            row = ET.Element(_tag("row"), r=str(row_num))
            index = next(
                (i for i, item in enumerate(sheet_data) if int(item.get("r")) > row_num),
                len(sheet_data),
            )
            sheet_data.insert(index, row)
            rows[row_num] = row
        cells = {item.get("r"): item for item in row if item.tag == _tag("c")}
        if row.get("spans"):
            right = max([REVIEW_LAST_COLUMN, *(coordinate_to_tuple(ref)[1] for ref in cells)])
            row.set("spans", f"1:{right}")
        note = "검토필요 유형: " + ", ".join(labels[key] for key in types)
        for field, label in (
            ("review_reason", "검토 사유"),
            ("classification_reason", "분류 판정 사유"),
            ("issues", "데이터 점검"),
            ("review_action", "확인/수정"),
        ):
            value = str(record.get(field, "") or "").strip()
            if value:
                note += f"\n{label}: {value}"
        for column, key in marks.items():
            ref = f"{get_column_letter(column)}{row_num}"
            cell = cells.get(ref)
            if cell is None:
                cell = ET.Element(_tag("c"), r=ref)
                index = next(
                    (
                        i
                        for i, item in enumerate(row)
                        if item.tag == _tag("c") and coordinate_to_tuple(item.get("r"))[1] > column
                    ),
                    len(row),
                )
                row.insert(index, cell)
            base = int(cell.get("s", "0"))
            color = colors[key].lstrip("#")
            cache_key = (base, color)
            if cache_key not in style_cache:
                if color not in fill_cache:
                    fill_cache[color] = len(fills)
                    fill = ET.SubElement(fills, _tag("fill"))
                    pattern = ET.SubElement(fill, _tag("patternFill"), patternType="solid")
                    ET.SubElement(pattern, _tag("fgColor"), rgb="FF" + color)
                    ET.SubElement(pattern, _tag("bgColor"), indexed="64")
                style = copy.deepcopy(formats[base])
                style.set("fillId", str(fill_cache[color]))
                style.set("applyFill", "1")
                style_cache[cache_key] = len(formats)
                formats.append(style)
            cell.set("s", str(style_cache[cache_key]))
        # One memo per record keeps row-wide fills compact and original notes intact.
        note_column = safe_column(row_num, fallback)
        if note_column not in marks:
            note_column = next(iter(marks))
        notes[f"{get_column_letter(note_column)}{row_num}"] = note
    if notes:
        fills.set("count", str(len(fills)))
        formats.set("count", str(len(formats)))
        parts[style_part] = _xml(styles, style_bytes)
        _add_comments(parts, sheet_part, sheet, notes)
        dimension = sheet.find(_tag("dimension"))
        if dimension is not None:
            left, top, right, bottom = range_boundaries(dimension.get("ref"))
            marked_rows = [coordinate_to_tuple(ref)[0] for ref in notes]
            dimension.set(
                "ref",
                f"{get_column_letter(min(left, 1))}{min(top, min(marked_rows))}:"
                f"{get_column_letter(max(right, REVIEW_LAST_COLUMN))}"
                f"{max(bottom, max(marked_rows))}",
            )
        parts[sheet_part] = _xml(sheet, sheet_bytes)


def export_source_review(
    result: AnalysisResult, path: str | Path, progress: Progress = noop_progress
) -> Path:
    """Write an annotated source copy, retaining formulas, VBA and unrelated ZIP parts."""
    target = Path(path).expanduser().resolve()
    source = result.loaded.path.resolve()
    if target == source:
        raise UserError("원본 파일을 덮어쓸 수 없습니다. 다른 저장 이름을 선택하세요.")
    if target.suffix.casefold() != source.suffix.casefold():
        raise UserError("검토표시 원본의 확장자는 원본 파일과 같아야 합니다.")
    progress(5, "원본 검토표시 파일 생성 중...")
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise UserError(
            "원본 파일을 읽을 수 없습니다. 원본 경로와 접근 권한을 확인하세요."
        ) from exc
    if hashlib.sha256(data).hexdigest() != result.loaded.file_hash:
        raise UserError(
            "분석 후 원본 파일이 변경되었습니다. 원본을 다시 읽고 분석한 뒤 출력하세요."
        )
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            parts = {info.filename: archive.read(info) for info in archive.infolist()}
            _highlight(parts, result)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(target, "w") as output:
                output.comment = archive.comment
                for info in archive.infolist():
                    output.writestr(info, parts.pop(info.filename))
                for name, value in parts.items():
                    output.writestr(name, value, compress_type=zipfile.ZIP_DEFLATED)
    except (zipfile.BadZipFile, ET.ParseError, KeyError, StopIteration, ValueError) as exc:
        raise UserError(
            "검토표시 원본을 생성할 수 없습니다. 원본 Excel 파일을 확인하고 다시 분석하세요."
        ) from exc
    progress(100, "원본 검토표시 파일 생성 완료")
    return target
