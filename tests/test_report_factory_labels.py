"""Factory prefixes distinguish converted line names in report charts."""

import pandas as pd

from report.charts import figure_for, tidy_label


def test_converted_names_keep_factory_in_top_line_chart():
    names = ["[남양주]ARCIL #1", "[김해]ARCIL #1"]
    table = pd.DataFrame({"equipment": names, "count": [10, 5]})
    figure = figure_for(table, "equipment", metric="count")
    labels = [label.get_text() for label in figure.axes[0].get_yticklabels()]
    assert set(labels) == set(names)
    assert table.equipment.tolist() == names


def test_factory_prefix_is_not_added_twice_or_removed():
    assert tidy_label("[남양주]ARCIL #1") == "[남양주]ARCIL #1"
    assert tidy_label("ARCIL #1") == "ARCIL #1"
