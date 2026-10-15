from __future__ import annotations
from core.models import LoadedData, AnalysisOptions, AnalysisResult, Progress, noop_progress
from core.preprocessing import standardize
from core.analyzer import analyze
from core.i18n import K

def run_analysis(loaded: LoadedData, config: dict, options: AnalysisOptions,
                 progress: Progress = noop_progress) -> AnalysisResult:
    records=standardize(loaded,config,options,progress)
    progress(80,K['processing'])
    result=analyze(loaded,records,config,options)
    progress(100,K['done'])
    return result
