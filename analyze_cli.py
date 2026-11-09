"""Command-line entry point for analysis and its three output files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.config import ConfigStore
from core.excel_loader import load_excel
from core.models import AnalysisOptions, UserError
from core.service import run_analysis
from report.export_bundle import export_bundle


def name_override(value: str) -> tuple[str, str]:
    """Parse a name assignment before creating or changing a user profile."""
    code, separator, name = value.partition("=")
    if not separator or not code.strip():
        raise argparse.ArgumentTypeError("--set-name must be CODE=DISPLAY_NAME")
    return code, name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline Excel equipment failure analyzer")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace existing analysis, PDF and review copy"
    )
    parser.add_argument("--sheet")
    parser.add_argument("--header-row", type=int)
    parser.add_argument("--scope", choices=("fault", "all"), default="fault")
    parser.add_argument("--factory", help="Only include the exact resolved factory name")
    parser.add_argument("--team", help="Only include the exact assigned team name")
    parser.add_argument(
        "--basis",
        choices=("mapped", "group", "factory", "team", "target", "registered", "family"),
        default="mapped",
    )
    parser.add_argument(
        "--set-name", action="append", type=name_override, default=[], metavar="CODE=DISPLAY_NAME"
    )
    parser.add_argument(
        "--name-source",
        choices=("line", "equipment"),
        help="Code source for --set-name (otherwise use the saved choice and available columns)",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    store = ConfigStore(args.data_dir)
    config = store.load()
    loaded = load_excel(
        args.input,
        config["column_mapping"],
        args.sheet,
        args.header_row,
        mapping_lookup=store.saved_mapping,
    )
    if args.set_name or args.name_source:
        from core.equipment_names import active_name_mapping, effective_name_source

        names = dict(config["equipment_names"])
        if args.name_source:
            names["source"] = args.name_source
        source = args.name_source or effective_name_source(loaded, names)
        mapping = active_name_mapping(None, {**names, "source": source}).copy()
        mapping.update(args.set_name)
        store.save_equipment_names(mapping, source=source)
        config = store.load()
    options = AnalysisOptions(
        scope=args.scope, equipment_basis=args.basis, factory=args.factory, team=args.team
    )
    result = run_analysis(loaded, config, options)
    paths = export_bundle(result, args.output, overwrite=args.overwrite)
    print(f"Rows: {result.metrics['selected_rows']}; minutes: {result.metrics['total_minutes']}")
    print(paths.excel)
    print(paths.pdf)
    if paths.source_review is not None:
        print(paths.source_review)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except UserError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
