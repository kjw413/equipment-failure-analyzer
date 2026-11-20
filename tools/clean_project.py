"""Preview disposable project caches; pass --apply to remove approved targets."""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHES = {"build", ".pytest_cache", ".ruff_cache"}
PRESERVED = {".git", ".venv", "config", "source", "wheels", "output", "outputs", "dist", "tmp"}
VALIDATION_FOLDERS = (
    "catalog_activation_1_8_0",
    "catalog_application_20261020",
    "rollback_1_7_2",
    "rules_report_validation",
    "ui_1_9_0",
)
LOCAL_VALIDATION_FOLDERS = ("tmp/demo", "tmp/qa")


@dataclass
class Target:
    path: Path
    files: int = 0
    size: int = 0
    refusal: str = ""


def reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def contained(path: Path) -> None:
    """Check every ancestor before resolving, so external links are never followed."""
    relative = path.relative_to(ROOT)
    if not relative.parts:
        raise ValueError("the project root cannot be removed")
    current = ROOT
    for part in relative.parts:
        current /= part
        if reparse(current.lstat()):
            raise ValueError("a symlink or Windows reparse point is present")
    if not path.resolve().is_relative_to(ROOT):
        raise ValueError("the target is outside the project")


def tracked_files() -> tuple[set[str], str]:
    git = shutil.which("git")
    has_git = os.path.lexists(ROOT / ".git")
    if git is None:
        return set(), "Git is unavailable; tracked files cannot be checked" if has_git else ""
    try:
        result = subprocess.run(
            [git, "-C", str(ROOT), "ls-files", "--cached", "-z", "--", "."],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return set(), f"Git check failed: {error}"
    if result.returncode:
        if has_git or b"not a git repository" not in result.stderr.lower():
            return set(), "Git could not check tracked files"
        return set(), ""
    return {
        os.path.normcase(os.path.normpath(os.fsdecode(name)))
        for name in result.stdout.split(b"\0")
        if name
    }, ""


def inspect(path: Path, tracked: set[str], git_error: str) -> Target:
    target = Target(path)
    try:
        contained(path)
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise ValueError("the target is not a directory")
        relative = os.path.normcase(os.path.normpath(str(path.relative_to(ROOT))))
        if any(name == relative or name.startswith(relative + os.sep) for name in tracked):
            raise ValueError("the target contains Git-tracked files")
        if git_error:
            raise ValueError(git_error)

        def count(directory: Path) -> None:
            if reparse(directory.lstat()):
                raise ValueError("a symlink or Windows reparse point is present")
            with os.scandir(directory) as entries:
                for entry in entries:
                    info = entry.stat(follow_symlinks=False)
                    if reparse(info):
                        raise ValueError("a symlink or Windows reparse point is present")
                    if stat.S_ISDIR(info.st_mode):
                        count(Path(entry.path))
                    elif stat.S_ISREG(info.st_mode):
                        target.files += 1
                        target.size += info.st_size
                    else:
                        raise ValueError("a special filesystem entry is present")

        count(path)
    except (OSError, ValueError) as error:
        target.refusal = str(error)
    return target


def discover(validation_temp: bool) -> tuple[list[Path], list[str]]:
    candidates: set[Path] = set()
    warnings: list[str] = []

    def entries(directory: Path) -> list[os.DirEntry[str]]:
        try:
            with os.scandir(directory) as iterator:
                return list(iterator)
        except OSError as error:
            warnings.append(f"{directory.relative_to(ROOT)}: {error}")
            return []

    def walk(directory: Path) -> None:
        for entry in entries(directory):
            path = Path(entry.path)
            try:
                info = entry.stat(follow_symlinks=False)
                is_directory = stat.S_ISDIR(info.st_mode)
                if entry.name in {".git", ".venv"}:
                    continue
                if directory == ROOT:
                    if entry.name in PRESERVED:
                        continue
                    if entry.name in CACHES or entry.name.startswith(".pytest_tmp"):
                        if is_directory or reparse(info):
                            candidates.add(path)
                        continue
                if entry.name == "__pycache__" and (is_directory or reparse(info)):
                    candidates.add(path)
                elif is_directory and not reparse(info):
                    walk(path)
            except OSError as error:
                warnings.append(f"{path.relative_to(ROOT)}: {error}")

    walk(ROOT)
    if validation_temp:
        for name in LOCAL_VALIDATION_FOLDERS:
            path = ROOT / name
            if os.path.lexists(path):
                candidates.add(path)
        for name in VALIDATION_FOLDERS:
            directory = ROOT / "output" / name
            if not os.path.lexists(directory):
                continue
            try:
                contained(directory)
                if not directory.is_dir():
                    continue
            except (OSError, ValueError) as error:
                warnings.append(f"output/{name}: {error}")
                continue
            for entry in entries(directory):
                try:
                    info = entry.stat(follow_symlinks=False)
                    if entry.name.startswith("pytest_") and (
                        stat.S_ISDIR(info.st_mode) or reparse(info)
                    ):
                        candidates.add(Path(entry.path))
                except OSError as error:
                    warnings.append(f"output/{name}/{entry.name}: {error}")
    return sorted(candidates, key=lambda path: str(path).casefold()), warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="delete the approved cache folders")
    parser.add_argument(
        "--validation-temp",
        action="store_true",
        help="also include local QA work and pytest_* folders in known validation directories",
    )
    options = parser.parse_args()
    paths, warnings = discover(options.validation_temp)
    tracked, git_error = tracked_files()
    targets = [inspect(path, tracked, git_error) for path in paths]
    approved = [target for target in targets if not target.refusal]
    print(f"Project: {ROOT}")
    print("Mode: APPLY" if options.apply else "Mode: DRY RUN (nothing will be deleted)")
    for target in targets:
        relative = target.path.relative_to(ROOT)
        if target.refusal:
            print(f"REFUSE {relative}: {target.refusal}")
        else:
            print(f"CACHE  {relative}: {target.files:,} files, {target.size:,} bytes")
    for warning in warnings:
        print(f"WARNING {warning}")
    print(
        f"Approved: {len(approved)} folders, "
        f"{sum(target.files for target in approved):,} files, "
        f"{sum(target.size for target in approved):,} bytes"
    )
    refused = len(targets) - len(approved)
    if not options.apply:
        print("Use --apply to delete the approved folders.")
        return 1 if refused or warnings else 0

    removed = files = size = 0
    for target in approved:
        # Recheck containment, all entries and Git tracking immediately before deletion.
        current_tracked, current_error = tracked_files()
        current = inspect(target.path, current_tracked, current_error)
        if current.refusal:
            refused += 1
            print(f"REFUSE {target.path.relative_to(ROOT)}: {current.refusal}")
            continue
        try:
            shutil.rmtree(target.path)
        except OSError as error:
            refused += 1
            print(f"FAILED {target.path.relative_to(ROOT)}: {error}")
            continue
        removed += 1
        files += current.files
        size += current.size
    print(f"Removed: {removed} folders, {files:,} files, {size:,} bytes; refused/failed: {refused}")
    return 1 if refused or warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
