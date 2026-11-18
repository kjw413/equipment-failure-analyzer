import os

import pytest
from openpyxl import Workbook, load_workbook

from report.cache import FormulaCache


@pytest.mark.skipif(os.name != "nt", reason="Windows transient file-handle regression")
def test_cache_patch_retries_transient_lock_and_keeps_values(tmp_path, monkeypatch):
    path = tmp_path / "values.xlsx"
    book = Workbook()
    cache = FormulaCache()
    cache.set(book.active, "A1", "=1+2", 3)
    book.save(path)
    book.close()
    replace = os.replace
    blocked = True

    def locked_once(src, dst):
        nonlocal blocked
        if blocked:
            blocked = False
            raise PermissionError("temporary scanner handle")
        return replace(src, dst)

    monkeypatch.setattr("report.cache.os.replace", locked_once)
    cache.patch(path)
    result = load_workbook(path, data_only=True)
    assert result.active["A1"].value == 3
    result.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows persistent file-handle regression")
def test_cache_patch_preserves_original_when_lock_persists(tmp_path, monkeypatch):
    path = tmp_path / "values.xlsx"
    book = Workbook()
    book.active["A1"] = "original"
    book.save(path)
    book.close()
    before = path.read_bytes()

    def locked(src, dst):
        raise PermissionError("persistent lock")

    monkeypatch.setattr("report.cache.os.replace", locked)
    monkeypatch.setattr("report.cache.time.sleep", lambda _: None)
    with pytest.raises(PermissionError):
        FormulaCache().patch(path)
    assert path.read_bytes() == before
