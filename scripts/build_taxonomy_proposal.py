"""Create auditable masters, representative cases and an all-event draft run."""

# ruff: noqa: E402
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from taxonomy_rebuild_policy import ACTION_PATTERNS, MODES, compact, draft_classify, find_entities

OUT = ROOT / "output/taxonomy_rebuild_20261112"


def load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def identity(kind, name):
    return kind + "-" + hashlib.sha256(name.encode()).hexdigest()[:10].upper()


def base_name(name):
    return re.sub(r"\([^)]*(?:미상|현장명)\)", "", name).strip()


DECISIONS = {
    2: (
        "문맥 오분류",
        "차단기 떨어짐은 보호장치 동작. 단자함 교체와 고장 현상을 구분",
        "낙하·과부하 원인을 추정하지 않음. 끝의 '교'는 원문 절단 여부 확인",
    ),
    3: (
        "복수 부품",
        "부싱 마모와 체인 파손을 각각 후보로 보존",
        "복수 고장을 부싱 하나로 자동 대표시키지 않음",
    ),
    4: (
        "부품 종류",
        "센서(종류 미상)와 롤러 제어부 후보 확인",
        "아이마크라는 표현만으로 광전 방식 확정하지 않음",
    ),
    5: (
        "의심 표현",
        "퓨즈 이상은 관측, 오일펌프 쇼트는 의심으로 구분",
        "의심을 소손·단락 확정 정답으로 바꾸지 않음",
    ),
    6: ("대상 연결", "컨베어 / 구동축 / 손상·파손", "원문 구동축 파손 근거 사용"),
    7: ("현장 표현", "필러·충진기 / 히터 / 고장·이상, 조치=교체", "'나감'만으로 소손 추정 금지"),
    8: ("정보 부족", "'메인'만으로는 분류 불가", "원문 보완까지 미확정"),
    9: (
        "설비·부품 경계",
        "열풍건조기는 상세설비, 내부 부품은 미기재",
        "컨베어는 원본 위치로 보존. 열풍건조기를 부품에 추가하지 않음",
    ),
    10: (
        "계통과 부품",
        "프리저 / 석션 제어밸브 / 누설, 냉매 계통 참고",
        "과냉·누설 복수 현상과 밸브 정비 예정은 분리. ICM 정밀 모델은 원문 값 보존",
    ),
    11: (
        "설비·부품 경계",
        "컨베어 / 레일(종류 미상) / 이탈·풀림",
        "박스카운터는 등록 설비. 컨베어와 컨베어벨트 구별",
    ),
    12: (
        "상위·하위 구분",
        "스틱인서터 / 센서(종류 미상), 종류 근거가 있으면 세부 센서",
        "센서 오류와 정렬불량이 함께 있어 최종 대상 확인",
    ),
    13: (
        "다른 매체 구분",
        "냉각수 공급부 / 배관 / 손상·파손",
        "냉각수와 냉매는 동의어가 아님. 호스·강관 종류 추정 금지",
    ),
    14: ("명시 증상 누락", "성형기 / 히터 / 소손·단락", "'단락'을 명시 증상으로 인식"),
    15: (
        "조치·현상 분리",
        "멀티포장기 / 그리퍼·집게 / 현상 미기재, 조치=수리·정비",
        "정비했다는 기록만으로 고장·이상 증상 만들지 않음",
    ),
    16: (
        "복수 교체와 주 고장",
        "균질기 / 피스톤씰 / 손상·파손을 우선 검토",
        "컴프레션링·서포트링은 별도 부품으로 유지. 교체만으로 세 부품 동시 파손 추정 금지",
    ),
    17: (
        "분야와 부품 소속",
        "밸브 / 밸브 제어헤드 / 고장·이상, 전원 케이블 교체 별도",
        "씽크탑 별칭 유지. 설치 위치가 유체 밸브라고 제어헤드를 유체 고장으로 고정하지 않음",
    ),
    18: (
        "원문 증상 우선",
        "전기·제어 / 펌프 / 모터(종류 미상) / 소손·단락",
        "원본 기계파트·UHT는 참고. 소손을 교체로 대체하지 않음",
    ),
    19: (
        "설비 계층",
        "전기·제어 / 엔드씰러 / 히터 / 소손·단락, 조치=교체",
        "필러는 상위 설비로 보존. 엔드씰러를 세부 부품에 반복하지 않음",
    ),
    20: (
        "복수 부품",
        "컨베어 / 베어링·축의 마모를 각각 후보로 보존",
        "한 이력의 건수·정지시간은 한 번만 집계",
    ),
    21: (
        "현상 통합",
        "펌프 / 볼트 / 손상·파손, 조치=정비·연마",
        "파손·손상을 상위 현상으로 통합하고 원문 단어는 유지",
    ),
    22: (
        "에러코드",
        "씰러 / 세부 부품 미기재 / 통신·입출력 이상",
        "영문 network station 설명을 근거로 삼고 def0283만으로 PLC 카드 고장을 추정하지 않음",
    ),
    23: (
        "공통 의견",
        "독립 분류 축과 설비 내부 계층을 구분하고 표준명·별칭 관리",
        "의견 행을 실제 고장이력이나 정답으로 집계하지 않음",
    ),
}


def main():
    records, feedback = load("source_records.json"), load("review_cases.json")
    profile = load("phase1_source_profile.json")
    catalog = json.loads((ROOT / "config/classification_catalog.json").read_text(encoding="utf-8"))
    equipment = {
        x["name"]: {
            "name": x["name"],
            "family": "설비·모듈",
            "aliases": list(dict.fromkeys([x["name"], *x["aliases"]])),
            "treatment": "기존 설비명 유지",
        }
        for x in catalog["equipment_types"]
    }
    old_equipment_alias = {
        compact(a): x["name"]
        for x in catalog["equipment_types"]
        for a in [x["name"], *x["aliases"]]
    }
    parts, migration = {}, []
    moves = {
        "롤러컨베어": "컨베어",
        "브러시컨베어": "컨베어",
        "플렉시블컨베어": "컨베어",
        "도징펌프": "펌프",
        "로터리펌프": "펌프",
        "부스터펌프": "펌프",
        "진공펌프": "진공펌프",
        "에이징탱크": "탱크",
        "냉동기": "냉동기",
        "에어컨": "에어컨",
        "냉각 컴프레서": "컴프레서",
        "냉매공급부(세부 미상)": "냉매 공급부",
        "열교환기(종류 미상)": "열교환기",
        "브레이즈드열교환기": "열교환기",
        "오일쿨러": "오일쿨러",
        "커팅부(세부 미상)": "커팅부",
        "감속기(종류 미상)": "감속기",
        "인계부(세부 미상)": "인계부",
        "디스차지부(세부 미상)": "디스차지부",
        "컵 디스펜서": "디스펜서",
        "컵 디스태커": "컵 디스태커",
    }
    canonical = {"리데나": "오일씰", "열전대(써머커플)": "열전대", "단자대·블록단자": "단자대"}
    for row in catalog["categories"]:
        old = row["minor"]
        aliases = list(
            dict.fromkeys(
                [old, base_name(old), *row.get("matching_aliases", row.get("aliases", []))]
            )
        )
        destination = moves.get(old) or old_equipment_alias.get(compact(base_name(old)))
        if destination:
            entity = equipment.setdefault(
                destination,
                {
                    "name": destination,
                    "family": "설비·모듈",
                    "aliases": [],
                    "treatment": "부품에서 설비·모듈로 이동",
                },
            )
            entity["aliases"] = list(dict.fromkeys([*entity["aliases"], *aliases]))
            migration.append(
                {
                    "old_part": old,
                    "old_group": row["middle"],
                    "new_axis": "상세설비",
                    "new_name": destination,
                    "reason": "기능 단위 본체·모듈이며 세부 부품과 중복하지 않음",
                }
            )
            continue
        new = "제품·자재" if row["middle"] == "제품·자재" else canonical.get(old, old)
        family = (
            "씰·패킹·링"
            if row["middle"] == "씰·패킹"
            else "제어헤드"
            if new == "밸브 제어헤드"
            else row["middle"]
        )
        entity = parts.setdefault(
            new,
            {
                "name": new,
                "family": family,
                "aliases": [],
                "original_domain": row["major"],
                "old_names": [],
                "treatment": "종류 미상 표기 유지" if "미상" in new else "유지",
                "caution": row.get("caution", ""),
            },
        )
        entity["aliases"] = list(dict.fromkeys([new, *entity["aliases"], *aliases]))
        entity["old_names"].append(old)
        if new == "밸브 제어헤드":
            entity["original_domain"] = "전기·제어"
            entity["treatment"] = "고장 분야 전기·제어, 밸브 설치 계통은 별도"
        if new != old:
            entity["treatment"] = "표준명 통합·원문 별칭 보존"
            migration.append(
                {
                    "old_part": old,
                    "old_group": row["middle"],
                    "new_axis": "세부 부품",
                    "new_name": new,
                    "reason": entity["treatment"],
                }
            )
    additions = [
        ("상세설비", "열풍건조기", "설비·모듈", ["열풍건조기", "열풍 건조기"]),
        ("상세설비", "냉각수 공급부", "설비·모듈", ["냉각수공급부", "냉각수공급라인"]),
        ("상세설비", "밸브", "설비·모듈", ["밸브", "버터밸브", "buttervalve"]),
        (
            "세부 부품",
            "석션 제어밸브",
            "밸브·액추에이터",
            ["썩션자동컨트롤밸브", "석션자동컨트롤밸브", "석션밸브", "썩션밸브", "icm밸브"],
        ),
    ]
    for axis, name, family, aliases in additions:
        target = equipment if axis == "상세설비" else parts
        target[name] = {
            "name": name,
            "family": family,
            "aliases": aliases,
            "treatment": "3개년 원문·수기 의견으로 추가",
            "original_domain": "온도·냉각" if name == "석션 제어밸브" else "",
            "caution": "매체·용도는 원문 근거가 있을 때만 사용",
        }
    parts["배관"]["aliases"].extend(["냉각수공급부라인", "냉각수공급라인", "냉각수라인"])
    for group, prefix in ((equipment, "EQ"), (parts, "PT")):
        for entity in group.values():
            entity["id"] = identity(prefix, entity["name"])
            counts, refs = Counter(), []
            for record in records:
                if find_entities(compact(record["description"]), [entity]):
                    counts[record["year"]] += 1
                    if len(refs) < 3:
                        refs.append(record["ref"])
            entity["mentions_by_year"] = dict(counts)
            entity["mentions"] = sum(counts.values())
            entity["example_refs"] = refs
            entity["evidence_status"] = "원문 출현" if refs else "현 자료 미출현·예비 항목"
            if not refs:
                entity["treatment"] += "; 예비 목록에서 유지·기본 선택 목록 제외 제안"
    alias_owners = defaultdict(set)
    aliases = []
    for kind, group in (("상세설비", equipment), ("세부 부품", parts)):
        for entity in group.values():
            for alias in entity["aliases"]:
                alias_owners[(kind, compact(alias))].add(entity["name"])
                aliases.append(
                    {
                        "axis": kind,
                        "alias": alias,
                        "canonical": entity["name"],
                        "id": entity["id"],
                        "rule": "긴 구체명 우선; 축·키는 뒤에 현상이 명시된 경우만 단일 글자 매칭",
                    }
                )
    collisions = [
        {"axis": k[0], "alias": k[1], "owners": sorted(v)}
        for k, v in alias_owners.items()
        if len(v) > 1
    ]
    policy = {
        "version": "proposal_2026-11-12",
        "status": "원문 기반 검토안·운영 미적용",
        "domains": [
            "기계",
            "전기·제어",
            "공압·진공",
            "유체·배관",
            "온도·냉각",
            "공정·운전",
            "분야 미상",
        ],
        "equipment": list(equipment.values()),
        "parts": list(parts.values()),
        "modes": [{"name": n, "pattern": p} for n, p in MODES],
        "actions": [{"name": n, "pattern": p} for n, p in ACTION_PATTERNS],
        "alias_collisions": collisions,
        "migrations": migration,
    }
    save("phase2_taxonomy_proposal.json", policy)
    save("phase2_aliases.json", aliases)
    baseline = {(x["year"], int(x["source_row"])): x for x in load("baseline_records.json")}
    draft = []
    for record in records:
        result = draft_classify(
            record["description"], record["mid"], policy["equipment"], policy["parts"]
        )
        old = baseline[(record["year"], record["row"])]
        first = result["candidates"][0] if len(result["candidates"]) == 1 else {}
        old_path = [old.get(k, "") for k in ("major", "detail_equipment", "middle", "minor")]
        new_path = [first.get(k, "") for k in ("major", "detail_equipment", "middle", "minor")]
        draft.append(
            {
                **record,
                **result,
                "baseline_path": old_path,
                "baseline_status": old["status"],
                "baseline_record_id": old["record_id"],
                "baseline_event_id": old["event_id"],
                "single_candidate_path": new_path,
                "changed": bool(first) and old_path != new_path,
            }
        )
    save("phase4_all_event_draft.json", draft)
    by_ref = {x["ref"]: x for x in draft}
    cases = []
    for row in feedback:
        key, decision, caution = DECISIONS[row["row"]]
        linked = [by_ref[ref] for ref in row["source_refs"]]
        result = (
            draft_classify(row["description"], row["mid"], policy["equipment"], policy["parts"])
            if row["description"]
            else {"candidates": [], "actions": [], "status": "공통 의견", "review_reasons": []}
        )
        cases.append(
            {
                **row,
                "issue": key,
                "proposed_decision": decision,
                "caution": caution,
                "draft": result,
                "source_match_count": len(linked),
                "validation_role": "기준 설계 사례·정답 미합의",
            }
        )
    design_refs = {ref for case in cases for ref in case["source_refs"]}
    validation = []
    design_texts = {compact(x["description"]) for x in cases if x["description"]}
    for year in (2024, 2025, 2026):
        pools = defaultdict(list)
        for row in draft:
            if (
                row["year"] != year
                or row["ref"] in design_refs
                or compact(row["description"]) in design_texts
            ):
                continue
            pools["단일 후보" if row["status"] == "단일 근거 후보·미확정" else "검토 후보"].append(
                row
            )
        for name, rows in pools.items():
            for row in sorted(rows, key=lambda x: hashlib.sha256(x["ref"].encode()).hexdigest())[
                :10
            ]:
                validation.append(
                    {
                        **row,
                        "sample_stratum": f"{year} {name}",
                        "human_major": "",
                        "human_equipment": "",
                        "human_part": "",
                        "human_mode": "",
                        "human_review": "",
                        "validation_role": "설계 사례 제외·별도 수기 검수 필요",
                    }
                )
    save("phase3_representative_cases.json", cases)
    save("phase4_independent_review_sample.json", validation)
    checks = {
        "source_rows_preserved": len(draft) == profile["rows"] == 3493,
        "source_refs_unique": len(by_ref) == len(draft),
        "baseline_record_ids_unique": len({x["baseline_record_id"] for x in draft}) == len(draft),
        "minutes_preserved": abs(sum(x["minutes"] for x in draft) - profile["minutes"]) < 1e-8,
        "no_actions_as_modes": not ({n for n, _ in ACTION_PATTERNS} & {n for n, _ in MODES}),
        "review_sample_excludes_design_texts": all(
            compact(x["description"]) not in design_texts for x in validation
        ),
        "feedback_all_traced": len(cases) == len(feedback),
    }
    summary = {
        "checks": checks,
        "operating_profile_changed": False,
        "equipment_items": len(equipment),
        "part_items": len(parts),
        "active_equipment": sum(x["mentions"] > 0 for x in equipment.values()),
        "active_parts": sum(x["mentions"] > 0 for x in parts.values()),
        "moved_or_merged": len(migration),
        "alias_rows": len(aliases),
        "alias_collisions": collisions,
        "mode_items": len(MODES),
        "action_items": len(ACTION_PATTERNS),
        "feedback_cases": len(cases),
        "independent_review_sample": len(validation),
        "status_counts": dict(Counter(x["status"] for x in draft)),
        "reason_counts": dict(Counter(reason for x in draft for reason in x["review_reasons"])),
        "candidate_changes": sum(x["changed"] for x in draft),
        "years": [
            {
                "year": year,
                "rows": sum(x["year"] == year for x in draft),
                "minutes": sum(x["minutes"] for x in draft if x["year"] == year),
                "single_candidates": sum(
                    x["year"] == year and x["status"] == "단일 근거 후보·미확정" for x in draft
                ),
            }
            for year in (2024, 2025, 2026)
        ],
        "accuracy": None,
        "accuracy_note": "설계 사례는 정답 미합의. 별도 검수 표본의 담당자 정답 입력 전 정확도는 측정하지 않음.",
    }
    save("phase4_validation_summary.json", summary)
    assert all(checks.values()), checks
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
