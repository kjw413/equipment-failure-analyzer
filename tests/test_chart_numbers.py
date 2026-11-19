from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pandas as pd
import pytest
from test_report_issue_views import organization_result as organization_result

from report.chart_numbers import format_chart_numbers
from report.charts import figure_for
from report.excel_report import export_report

NS = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}


@pytest.mark.parametrize("prefix", ["", "c:"])
def test_chart_formats_keep_native_xml_values_dates_and_percentages(prefix):
    p = prefix
    declaration = f'xmlns{":c" if p else ""}="{NS["c"]}"'
    raw = (
        f"<{p}chartSpace {declaration}><{p}chart><{p}plotArea>"
        f'<{p}valAx><{p}axId val="1"/><{p}scaling/><{p}axPos val="b"/>'
        f'<{p}majorTickMark val="none"/><{p}crossAx val="2"/></{p}valAx>'
        f'<{p}dLbls><{p}dLbl><{p}idx val="0"/></{p}dLbl>'
        f'<{p}showVal val="1"/></{p}dLbls>'
        f'<{p}numCache><{p}formatCode>General</{p}formatCode><{p}pt idx="0">'
        f"<{p}v>12345.6</{p}v></{p}pt></{p}numCache>"
        f'<{p}catAx><{p}numFmt formatCode="yyyy-mm" sourceLinked="1"/></{p}catAx>'
        f'<{p}valAx><{p}numFmt formatCode="0.0%" sourceLinked="0"/></{p}valAx>'
        f"</{p}plotArea></{p}chart></{p}chartSpace>"
    ).encode()
    output = format_chart_numbers(raw)
    assert format_chart_numbers(output) == output
    tree = ET.fromstring(output)
    assert tree.find(".//c:v", NS).text == "12345.6"
    assert tree.find(".//c:formatCode", NS).text == "#,##0"
    assert tree.find(".//c:catAx/c:numFmt", NS).get("formatCode") == "yyyy-mm"
    assert tree.findall(".//c:valAx", NS)[-1].find("c:numFmt", NS).get("formatCode") == "0.0%"
    for path in (".//c:dLbls/c:numFmt", ".//c:dLbl/c:numFmt", ".//c:valAx/c:numFmt"):
        assert tree.find(path, NS).attrib == {"formatCode": "#,##0", "sourceLinked": "0"}


@pytest.mark.parametrize("kind", ["bar", "trend", "pareto"])
def test_pdf_chart_value_axes_use_grouped_integer_ticks(kind):
    figure = figure_for(
        pd.DataFrame({"period": ["2026-01", "2026-02"], "count": [12000, 23456]}),
        "period",
        "count",
        kind,
    )
    try:
        axis = figure.axes[0].xaxis if kind == "bar" else figure.axes[0].yaxis
        assert axis.get_major_formatter()(12000) == "12,000"
        assert axis.get_major_formatter()(0) == "0"
        assert axis.get_major_formatter()(-1234).replace("−", "-") == "-1,234"
    finally:
        figure.clear()


def test_every_exported_excel_chart_has_explicit_grouped_integer_format(
    organization_result, tmp_path
):
    path = export_report(organization_result, tmp_path / "formatted.xlsm")
    with ZipFile(path) as archive:
        charts = [
            ET.fromstring(archive.read(name))
            for name in archive.namelist()
            if name.startswith("xl/charts/chart") and name.endswith(".xml")
        ]
    assert len(charts) == 6
    for chart in charts:
        for path in (".//c:valAx", ".//c:dLbls", ".//c:dLbl"):
            for node in chart.findall(path, NS):
                fmt = node.find("c:numFmt", NS)
                assert fmt is not None
                assert fmt.attrib == {"formatCode": "#,##0", "sourceLinked": "0"}
