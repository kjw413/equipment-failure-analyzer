"""Approved independent axes and conservative spelling updates survive upgrades."""

import copy
import json
import shutil
from pathlib import Path

from core.defaults_merge import DefaultsMerger, merge_public_taxonomy
from core.parsing import prepare_text

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


def payload(name):
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


def test_public_master_covers_approved_axes_without_repeating_machine_bodies_as_parts():
    catalog = payload("classification_catalog.json")
    public = catalog["public_taxonomy"]
    parts = {row["name"]: row for row in public["parts"]}
    equipment = {row["name"] for row in catalog["equipment_types"]}
    assert catalog["output_schema"] == "equipment_part_failure_v3"
    assert catalog["catalog_version"] == "1.15.0"
    assert len(equipment) == 65 and len(parts) == 199
    assert len({row["family"] for row in parts.values()}) == 29
    assert len(public["domains"]) == 7 and "분야 미상" in public["domains"]
    assert len(public["modes"]) == 23 and "현상 미기재" in public["modes"]
    assert len(public["actions"]) == 7 and "교체" not in public["modes"]
    assert {name for group in public["equipment_groups"] for name in group["items"]} == equipment
    assert not {"컨베어", "열풍건조기", "냉각수 공급부", "엔드씰러"} & parts.keys()
    assert parts["밸브 제어헤드"]["family"] == "제어·통신부품"
    assert parts["오일씰"]["old_names"] == ["리데나"]
    assert "리데나" in parts["오일씰"]["aliases"]
    assert parts["광전센서"]["family"] == parts["센서(종류 미상)"]["family"] == "센서·계측"
    assert all(name in parts for name in ("오링", "피스톤씰", "가스켓", "컴프레션링", "서포트링"))
    assert {"냉매 공급부", "냉각수 공급부"} <= equipment


def test_spelling_normalization_keeps_diagnoses_and_distinct_media():
    normalization = payload("normalization.json")
    assert (
        prepare_text("그립퍼 브러쉬 리데나 써머커플", normalization)
        == "그리퍼 브러시 오일씰 열전대"
    )
    text = "차단기 떨어짐, 모터 나감, 베어링 정비. 냉매 공급부와 냉각수 공급부. PLC 카드 WAGO 31 이상 아님"
    normalized = prepare_text(text, normalization)
    assert normalized == text.casefold()
    assert "과부하" not in normalized and "소손" not in normalized and "낙하" not in normalized
    assert "냉매" in normalized and "냉각수" in normalized and "이상 아님" in normalized


def test_public_master_merge_preserves_edits_deletions_and_custom_choices():
    previous = payload("classification_catalog.json")["public_taxonomy"]
    user = copy.deepcopy(previous)
    bundled = copy.deepcopy(previous)
    removed = user["parts"].pop(0)["name"]
    changed = user["parts"][0]["name"]
    user["parts"][0]["aliases"].append("현장 전용 별칭")
    user["parts"].append(
        {"name": "현장 부품", "family": "현장 부품군", "aliases": [], "old_names": []}
    )
    bundled["parts"][1]["aliases"].append("새 기본 별칭")
    bundled["parts"][2]["aliases"].append("갱신 별칭")
    user["modes"].remove("부식")
    user["modes"].append("현장 현상")
    bundled["modes"].append("새 기본 현상")
    user["equipment_groups"][0]["items"].append("현장 설비")
    bundled["equipment_groups"][0]["items"].append("새 기본 설비")
    merged, kept = merge_public_taxonomy(user, bundled, previous)
    by_name = {row["name"]: row for row in merged["parts"]}
    assert removed not in by_name
    assert "현장 전용 별칭" in by_name[changed]["aliases"]
    assert "새 기본 별칭" not in by_name[changed]["aliases"]
    assert "갱신 별칭" in by_name[bundled["parts"][2]["name"]]["aliases"]
    assert "현장 부품" in by_name and kept >= 1
    assert "부식" not in merged["modes"]
    assert {"현장 현상", "새 기본 현상"} <= set(merged["modes"])
    assert {"현장 설비", "새 기본 설비"} <= set(merged["equipment_groups"][0]["items"])
    assert merge_public_taxonomy(merged, bundled, bundled)[0] == merged


def test_first_public_upgrade_preserves_legacy_equipment_customizations(tmp_path):
    previous = payload("defaults_history.json")["classification_catalog.equipment_types"]
    user = copy.deepcopy(payload("classification_catalog.json"))
    user.pop("public_taxonomy")
    user["output_schema"] = "equipment_part_symptom_v2"
    user["equipment_types"] = copy.deepcopy(previous[1:])
    edited = user["equipment_types"][0]["name"]
    user["equipment_types"][0]["aliases"].append("현장 전용 설비명")
    user["equipment_types"].append({"name": "현장 설비", "aliases": ["현장 설비"]})
    profile = tmp_path / "config"
    profile.mkdir()
    path = profile / "classification_catalog.json"
    path.write_text(json.dumps(user, ensure_ascii=False), encoding="utf-8")
    merger = DefaultsMerger(CONFIG, profile)
    merger.classification_catalog({})
    installed = json.loads(path.read_text(encoding="utf-8"))
    types = {row["name"]: row for row in installed["equipment_types"]}
    assert previous[0]["name"] not in types
    assert "현장 전용 설비명" in types[edited]["aliases"]
    assert {"현장 설비", "열풍건조기", "냉각수 공급부"} <= types.keys()
    assert "installed_public_taxonomy" in installed and "installed_equipment_types" in installed


def test_durable_public_baseline_preserves_customization_after_old_cache_reset(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    merger = DefaultsMerger(CONFIG, profile)
    merger.classification_catalog({})
    path = profile / "classification_catalog.json"
    user = json.loads(path.read_text(encoding="utf-8"))
    user["public_taxonomy"]["parts"][0]["aliases"].append("현장 전용 별칭")
    user["public_taxonomy"]["parts"].pop(1)
    deleted_name = user["installed_public_taxonomy"]["parts"][1]["name"]
    path.write_text(json.dumps(user, ensure_ascii=False), encoding="utf-8")
    revised_bundle = tmp_path / "bundle"
    shutil.copytree(CONFIG, revised_bundle)
    updated = json.loads(
        (revised_bundle / "classification_catalog.json").read_text(encoding="utf-8")
    )
    updated["public_taxonomy"]["parts"][0]["aliases"].append("새 기본 별칭")
    (revised_bundle / "classification_catalog.json").write_text(
        json.dumps(updated, ensure_ascii=False), encoding="utf-8"
    )
    DefaultsMerger(revised_bundle, profile).classification_catalog({})
    installed = json.loads(path.read_text(encoding="utf-8"))
    parts = {row["name"]: row for row in installed["public_taxonomy"]["parts"]}
    assert deleted_name not in parts
    assert "현장 전용 별칭" in installed["public_taxonomy"]["parts"][0]["aliases"]
    assert "새 기본 별칭" not in installed["public_taxonomy"]["parts"][0]["aliases"]
    before = path.read_bytes()
    DefaultsMerger(revised_bundle, profile).classification_catalog({})
    assert path.read_bytes() == before
