"""Run the repo's rule engine on all 3 years and save one record table."""

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO, WORK

sys.path.insert(0, str(REPO))
import pandas as pd

from core.config import ConfigStore
from core.excel_loader import load_excel
from core.models import AnalysisOptions
from core.service import run_analysis

S = WORK
store = ConfigStore(S / "profile")
config = store.load()
frames = []
for y in (2024, 2025, 2026):
    loaded = load_excel(
        S / f"data/y{y}.xlsx",
        config["column_mapping"],
        None,
        None,
        mapping_lookup=store.saved_mapping,
    )
    r = run_analysis(loaded, config, AnalysisOptions(scope="fault", equipment_basis="mapped"))
    d = r.selected.copy()
    d["year"] = y
    frames.append(d)
    print(y, len(r.all_records), len(d))
df = pd.concat(frames, ignore_index=True)
df.to_pickle(S / "exp" / "baseline.pkl")
print(list(df.columns))
