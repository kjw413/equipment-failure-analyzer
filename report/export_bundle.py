"""One atomic export route for analysis Excel, PDF and the annotated source copy."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.models import AnalysisResult, Progress, UserError, noop_progress
from report.excel_report import export_report
from report.pdf_report import export_pdf
from report.source_review import export_source_review


@dataclass(frozen=True)
class ReportFiles:
    excel: Path
    pdf: Path
    source_review: Path | None = None


def report_paths(excel_path: str | Path, source_path: str | Path | None = None) -> ReportFiles:
    excel = Path(excel_path).expanduser().resolve().with_suffix(".xlsx")
    source_suffix = Path(source_path).suffix.casefold() if source_path is not None else ".xlsx"
    if source_suffix not in (".xlsx", ".xlsm"):
        source_suffix = ".xlsx"
    return ReportFiles(
        excel,
        excel.with_name(excel.stem + "_최종보고서.pdf"),
        excel.with_name(excel.stem + "_원본_검토표시" + source_suffix),
    )


def _commit(staged: list[Path], targets: list[Path], staging: Path) -> None:
    """Restore every replaced target if committing any of the three files fails."""
    backups: dict[Path, Path] = {}
    for index, target in enumerate(targets):
        if target.exists():
            backup = staging / f"previous_{index}{target.suffix}"
            shutil.copy2(target, backup)
            backups[target] = backup
    replaced: list[Path] = []
    try:
        for temp, target in zip(staged, targets):
            os.replace(temp, target)
            replaced.append(target)
    except OSError as original:
        failed = []
        for target in reversed(replaced):
            try:
                if target in backups:
                    os.replace(backups[target], target)
                else:
                    target.unlink(missing_ok=True)
            except OSError:
                failed.append(target)
        if failed:
            # Preserve recovery data outside the temporary directory before cleanup.
            recovery = Path(tempfile.mkdtemp(prefix="EFA_recovery_", dir=targets[0].parent))
            for target, backup in backups.items():
                if backup.exists():
                    shutil.copy2(backup, recovery / target.name)
            raise UserError(
                "\uc800\uc7a5/\ubcf5\uad6c \uc911 \uc624\ub958\uac00 \ubc1c\uc0dd\ud588\uc2b5\ub2c8\ub2e4. \uae30\uc874 \ud30c\uc77c \ubc31\uc5c5 \ud655\uc778: "
                + str(recovery)
            ) from original
        raise


def export_bundle(
    result: AnalysisResult,
    excel_path: str | Path,
    progress: Progress = noop_progress,
    *,
    overwrite: bool = False,
) -> ReportFiles:
    """Create all three files from one immutable result snapshot, without source edits."""
    paths = report_paths(excel_path, result.loaded.path)
    targets = [paths.excel, paths.pdf, paths.source_review]
    if result.loaded.path.resolve() in targets:
        raise UserError(
            "\uc6d0\ubcf8 \ud30c\uc77c\uc744 \ub36e\uc5b4\uc4f8 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4. \ub2e4\ub978 \uc800\uc7a5 \uc774\ub984\uc744 \uc120\ud0dd\ud558\uc138\uc694."
        )
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise UserError(
            "\uc774\ubbf8 \uacb0\uacfc \ud30c\uc77c\uc774 \uc788\uc2b5\ub2c8\ub2e4. \ub2e4\ub978 \uc774\ub984\uc744 \uc120\ud0dd\ud558\uac70\ub098 \ub36e\uc5b4\uc4f0\uae30\ub97c \ud655\uc778\ud558\uc138\uc694.\n"
            + "\n".join(map(str, existing))
        )
    try:
        paths.excel.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".efa_export_", dir=paths.excel.parent
        ) as directory:
            staging = Path(directory)
            excel = export_report(
                result, staging / "analysis.xlsx", lambda n, t: progress(int(n * 0.55), t)
            )
            pdf = export_pdf(
                result, staging / "final.pdf", lambda n, t: progress(55 + int(n * 0.35), t)
            )
            source_review = export_source_review(
                result,
                staging / ("source_review" + paths.source_review.suffix),
                lambda n, t: progress(90 + int(n * 0.08), t),
            )
            # Check again after rendering, in case another process created a target.
            if not overwrite and any(path.exists() for path in targets):
                raise UserError(
                    "\uc800\uc7a5 \uc911 \uac19\uc740 \uc774\ub984\uc758 \ud30c\uc77c\uc774 \uc0dd\uacbc\uc2b5\ub2c8\ub2e4. \uc0c8 \uc774\ub984\uc73c\ub85c \ub2e4\uc2dc \uc800\uc7a5\ud558\uc138\uc694."
                )
            _commit([excel, pdf, source_review], targets, staging)
    except PermissionError as exc:
        raise UserError(
            "Excel/PDF\uac00 \uc5f4\ub824 \uc788\uac70\ub098 \uc800\uc7a5 \uad8c\ud55c\uc774 \uc5c6\uc2b5\ub2c8\ub2e4. \ucd9c\ub825 \ud30c\uc77c\uc744 \ub2eb\uace0 \ub2e4\uc2dc \uc2dc\ub3c4\ud558\uc138\uc694. \ucd9c\ub825 \uc644\ub8cc\ub85c \ucc98\ub9ac\ud558\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4."
        ) from exc
    progress(100, "Excel + PDF + 원본 검토표시 생성 완료")
    return paths
