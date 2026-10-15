"""Optional non-GUI entry point for validation and batch report generation."""
from __future__ import annotations
import argparse
from pathlib import Path
from core.config import ConfigStore
from core.excel_loader import load_excel
from core.models import AnalysisOptions
from core.service import run_analysis
from report.export_bundle import export_bundle


def main() -> int:
    parser=argparse.ArgumentParser(description='Offline Excel equipment failure analyzer')
    parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--overwrite',action='store_true',help='Replace an existing Excel/PDF pair')
    parser.add_argument('--sheet')
    parser.add_argument('--header-row',type=int)
    parser.add_argument('--scope',choices=('fault','all'),default='fault')
    parser.add_argument('--basis',choices=('mapped','target','registered','family'),default='mapped')
    parser.add_argument('--set-name',action='append',default=[],metavar='CODE=DISPLAY_NAME')
    args=parser.parse_args()
    store=ConfigStore(args.data_dir)
    if args.set_name:
        mapping=store.read('equipment_names.json')['mappings'].copy()
        for item in args.set_name:
            code,separator,name=item.partition('=')
            if not separator:parser.error('--set-name must be CODE=DISPLAY_NAME')
            mapping[code]=name
        store.save_equipment_names(mapping)
    config=store.load()
    loaded=load_excel(args.input,config['column_mapping'],args.sheet,args.header_row,mapping_lookup=store.saved_mapping)
    result=run_analysis(loaded,config,AnalysisOptions(scope=args.scope,equipment_basis=args.basis))
    paths=export_bundle(result,args.output,overwrite=args.overwrite)
    print(f'Rows: {result.metrics["selected_rows"]}; minutes: {result.metrics["total_minutes"]}')
    print(paths.excel)
    print(paths.pdf)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
