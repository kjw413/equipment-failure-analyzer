from __future__ import annotations

from core.analyzer import analyze
from core.i18n import K
from core.models import AnalysisOptions, AnalysisResult, LoadedData, Progress, noop_progress
from core.preprocessing import standardize


def run_analysis(
    loaded: LoadedData, config: dict, options: AnalysisOptions, progress: Progress = noop_progress
) -> AnalysisResult:
    records = standardize(loaded, config, options, progress)
    progress(80, K["processing"])
    result = analyze(loaded, records, config, options)
    progress(100, K["done"])
    return result
