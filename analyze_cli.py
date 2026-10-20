"""Command-line entry point for validation and paired Excel/PDF exports."""

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
        "--overwrite", action="store_true", help="Replace an existing Excel/PDF pair"
    )
    parser.add_argument("--sheet")
    parser.add_argument("--header-row", type=int)
    parser.add_argument("--scope", choices=("fault", "all"), default="fault")
    parser.add_argument(
        "--basis", choices=("mapped", "target", "registered", "family"), default="mapped"
    )
    parser.add_argument(
        "--set-name", action="append", type=name_override, default=[], metavar="CODE=DISPLAY_NAME"
    )
    return parser


def run(args: argparse.Namespace) -> int:
    store = ConfigStore(args.data_dir)
    if args.set_name:
        mapping = store.read("equipment_names.json")["mappings"].copy()
        mapping.update(args.set_name)
        store.save_equipment_names(mapping)
    config = store.load()
    loaded = load_excel(
        args.input,
        config["column_mapping"],
        args.sheet,
        args.header_row,
        mapping_lookup=store.saved_mapping,
    )
    options = AnalysisOptions(scope=args.scope, equipment_basis=args.basis)
    result = run_analysis(loaded, config, options)
    paths = export_bundle(result, args.output, overwrite=args.overwrite)
    print(f"Rows: {result.metrics['selected_rows']}; minutes: {result.metrics['total_minutes']}")
    print(paths.excel)
    print(paths.pdf)
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
