"""Add the audited, data-free VBA search UI without resaving native chart XML."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from core.config import resource_root

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT = "http://schemas.openxmlformats.org/package/2006/content-types"
VBA_REL = "http://schemas.microsoft.com/office/2006/relationships/vbaProject"


def _package_xml(root: ET.Element) -> bytes:
    """OPC metadata uses its package namespace as the default, including strict readers."""
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    local = root.tag.rsplit("}", 1)[-1].encode("ascii")
    match = re.search(rb"<([A-Za-z_][\w]*):" + local + rb"\b", data)
    if match:
        prefix = match[1]
        data = data.replace(b"<" + prefix + b":", b"<")
        data = data.replace(b"</" + prefix + b":", b"</")
        data = data.replace(b"xmlns:" + prefix + b"=", b"xmlns=")
    return data


def embed_search_project(path: Path) -> None:
    manifest = json.loads(
        (resource_root() / "config/report_search_vba.json").read_text(encoding="utf-8")
    )
    workbook_codename = manifest["workbook_codename"]
    project = (resource_root() / "config/report_search_vba.bin").read_bytes()
    if not project.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        raise ValueError("Invalid report search VBA project")
    fd, filename = tempfile.mkstemp(suffix=".xlsm", dir=path.parent)
    os.close(fd)
    temporary = Path(filename)
    try:
        with ZipFile(path) as source, ZipFile(temporary, "w", ZIP_DEFLATED) as dest:
            for entry in source.infolist():
                data = source.read(entry.filename)
                if entry.filename == "[Content_Types].xml":
                    root = ET.fromstring(data)
                    for item in root:
                        if item.get("PartName") == "/xl/workbook.xml":
                            item.set(
                                "ContentType",
                                "application/vnd.ms-excel.sheet.macroEnabled.main+xml",
                            )
                    ET.SubElement(
                        root,
                        f"{{{CONTENT}}}Override",
                        {
                            "PartName": "/xl/vbaProject.bin",
                            "ContentType": "application/vnd.ms-office.vbaProject",
                        },
                    )
                    data = _package_xml(root)
                elif entry.filename == "xl/_rels/workbook.xml.rels":
                    root = ET.fromstring(data)
                    ids = {item.get("Id") for item in root}
                    number = 1
                    while f"rId{number}" in ids:
                        number += 1
                    ET.SubElement(
                        root,
                        f"{{{REL}}}Relationship",
                        {
                            "Id": f"rId{number}",
                            "Type": VBA_REL,
                            "Target": "vbaProject.bin",
                        },
                    )
                    data = _package_xml(root)
                elif entry.filename == "xl/workbook.xml":
                    root = ET.fromstring(data)
                    properties = root.find(f"{{{MAIN}}}workbookPr")
                    if properties is None:
                        properties = ET.Element(f"{{{MAIN}}}workbookPr")
                        root.insert(0, properties)
                    properties.set("codeName", workbook_codename)
                    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                dest.writestr(entry, data)
            dest.writestr("xl/vbaProject.bin", project)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
