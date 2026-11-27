"""Atomically export the analysis workbook."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.models import AnalysisResult, Progress, UserError, noop_progress
from report.excel_report import export_report


@dataclass(frozen=True)
class ReportFiles:
    excel: Path
    source_review: Path | None = None


def report_paths(excel_path: str | Path, source_path: str | Path | None = None) -> ReportFiles:
    excel = Path(excel_path).expanduser().resolve()
    if excel.suffix.casefold() not in (".xlsx", ".xlsm"):
        excel = excel.with_suffix(".xlsm")
    else:
        excel = excel.with_suffix(excel.suffix.casefold())
    return ReportFiles(excel)


def export_bundle(
    result: AnalysisResult,
    excel_path: str | Path,
    progress: Progress = noop_progress,
    *,
    overwrite: bool = False,
) -> ReportFiles:
    """Save the Excel workbook from one analysis snapshot."""
    paths = report_paths(excel_path)
    target = paths.excel
    if result.loaded.path.resolve() == target:
        raise UserError(
            "\uc6d0\ubcf8 \ud30c\uc77c\uc744 \ub36e\uc5b4\uc4f8 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4. \ub2e4\ub978 \uc800\uc7a5 \uc774\ub984\uc744 \uc120\ud0dd\ud558\uc138\uc694."
        )
    if target.exists() and not overwrite:
        raise UserError(
            f"이미 결과 파일이 있습니다. 다른 이름을 선택하거나 덮어쓰기를 확인하세요.\n{target}"
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".efa_export_", dir=target.parent) as directory:
            staged = export_report(
                result,
                Path(directory) / ("analysis" + target.suffix),
                lambda n, t: progress(int(n * 0.95), t),
            )
            try:
                if overwrite:
                    os.replace(staged, target)
                elif os.name == "nt":
                    os.rename(staged, target)
                else:
                    # POSIX rename replaces an existing destination, so publish with a link.
                    os.link(staged, target)
            except FileExistsError as exc:
                raise UserError(
                    "저장 중 같은 이름의 파일이 생겼습니다. 새 이름으로 다시 저장하세요."
                ) from exc
    except PermissionError as exc:
        raise UserError(
            "Excel 파일이 열려 있거나 저장 권한이 없습니다. 파일을 닫고 다시 시도하세요."
        ) from exc
    progress(100, "Excel 생성 완료 (원본 검토표시는 Excel 별첨)")
    return paths
