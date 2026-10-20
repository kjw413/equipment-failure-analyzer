"""CLI argument validation and user-facing error handling."""

import pytest

import analyze_cli
from core.config import ConfigStore
from report.export_bundle import ReportFiles


def test_invalid_name_argument_does_not_create_profile(tmp_path, capsys):
    profile = tmp_path / "unused-profile"
    with pytest.raises(SystemExit) as exc:
        analyze_cli.main(
            [
                "input.xlsx",
                "--output",
                "out.xlsx",
                "--data-dir",
                str(profile),
                "--set-name",
                "missing-equals",
            ]
        )
    assert exc.value.code == 2
    assert not profile.exists()
    assert "CODE=DISPLAY_NAME" in capsys.readouterr().err


def test_missing_input_reports_user_error_without_traceback(tmp_path, capsys):
    status = analyze_cli.main(
        [
            str(tmp_path / "missing.xlsx"),
            "--output",
            str(tmp_path / "out.xlsx"),
            "--data-dir",
            str(tmp_path / "profile"),
        ]
    )
    captured = capsys.readouterr()
    assert status == 1
    assert captured.err.startswith("Error: ")
    assert "Traceback" not in captured.err
    assert not (tmp_path / "out.xlsx").exists()


def test_name_assignments_and_export_options(input_file, tmp_path, monkeypatch, capsys):
    profile = tmp_path / "profile"
    target = tmp_path / "out.xlsx"
    seen = {}

    def export(result, output, *, overwrite):
        seen.update(result=result, output=output, overwrite=overwrite)
        return ReportFiles(output, output.with_suffix(".pdf"))

    monkeypatch.setattr(analyze_cli, "export_bundle", export)
    status = analyze_cli.main(
        [
            str(input_file),
            "--output",
            str(target),
            "--data-dir",
            str(profile),
            "--scope",
            "all",
            "--basis",
            "registered",
            "--overwrite",
            "--set-name",
            "IF18115=Renamed=2",
            "--set-name",
            "IF20000=",
        ]
    )
    assert status == 0
    names = ConfigStore(profile).read("equipment_names.json")["mappings"]
    assert names == {"IF18115": "Renamed=2"}
    assert seen["output"] == target and seen["overwrite"] is True
    assert seen["result"].options.scope == "all"
    assert seen["result"].options.equipment_basis == "registered"
    assert seen["result"].metrics["selected_rows"] == 5
    assert "Rows: 5" in capsys.readouterr().out
