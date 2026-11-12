"""Compare immutable production-audit exports without importing classifier code.

This reports coverage/workload and literal-evidence screening, never accuracy.
The complete audit records for every changed/promoted row remain in the JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AXES = ("major", "detail_equipment", "middle", "minor")
AXIS_LABELS = ("고장 분야", "상세설비", "세부 부품", "고장 현상")
UNKNOWN = {
    "",
    "미기재",
    "미분류",
    "분야 미상",
    "상세설비 미상",
    "상세설비 미기재",
    "세부 부품 미기재",
    "현상 미기재",
    "증상 미기재",
    "부위 미기재",
}
BUCKETS = ("complete_auto", "partial_auto", "review", "unmatched", "manual", "nonfault", "other")
BUCKET_LABELS = {
    "complete_auto": "완전 자동분류",
    "partial_auto": "부분 자동분류",
    "review": "실제 검토필요",
    "unmatched": "미일치·코드 미기입",
    "manual": "사용자 확정",
    "nonfault": "분류대상 외",
    "other": "기타 상태",
}
AUTO_STATUSES = {"규칙분류", "부분분류", "부분자동분류"}
ACTION_WORDS = {
    "교체": r"교체|교환|replaced",
    "수리·정비": r"수리(?!크)|정비|가공|보수|용접|보강|연마|repair",
    "조정": r"조정|조절|세팅|셋팅|수정|교정|adjusted",
    "점검": r"점검|확인|inspected",
    "청소·급유": r"청소|세척|급유|도포",
    "체결·조립": r"체결|재조임|분해|조립",
    "리셋·재가동": r"리셋|reset|재부팅|온오프|재투입|재가동|생산재개|복구",
}
# These deliberately broad screens identify passages to inspect; they do not
# reproduce the production binding/selection policy or certify semantic truth.
RISK_WORDS = re.compile(
    r"예정|계획|추후|예방|정상|이상\s*없|문제\s*없|의심|추정|확인\s*필요|미실시|하지\s*않",
    re.I,
)
FALLBACK_FAILURE = re.compile(
    r"파손|손상|마모|부식|변형|풀림|이탈|누설|누수|누유|리크|막힘|걸림|단선|소손|단락|쇼트|"
    r"트립|과부하|과전류|오작동|미작동|불량|감지|통신|진동|소음|과열|결빙|압력저하|"
    r"오염|이물|타이밍|낙하|고장|이상|에러|오류|알람|나감|failed|fault|error|leak|broken",
    re.I,
)
COMPARE_FIELDS = (
    *AXES,
    "status",
    "classification_mode",
    "classification_missing_fields",
    "part_group",
    "repair_actions",
    "review_code",
    "evidence",
    "classification_reason",
    "issues",
    "classification_candidates",
    "component_details",
    "part_count",
    "component_count",
)


def compact(value):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", str(value or "")).casefold())


def array(value):
    if isinstance(value, str):
        value = json.loads(value) if value.strip() else []
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Expected a JSON array in candidate/component details")
    return value


def unknown(value):
    return str(value or "").strip() in UNKNOWN


def known_axes(row):
    return {
        field: {"value": row.get(field, ""), "known": not unknown(row.get(field))} for field in AXES
    }


def bucket(row):
    status = row.get("status", "")
    if status == "사용자확정":
        return "manual"
    if status == "검토필요":
        return "review"
    if status in {"규칙 미일치", "비가동코드 미기입"}:
        return "unmatched"
    if status == "분류대상 외" or row.get("kind", "고장") != "고장":
        return "nonfault"
    if status in AUTO_STATUSES:
        # Re-express the old baseline under the same completeness definition.
        # Old status=규칙분류 did include unknown equipment/parts.
        if status != "규칙분류" or any(unknown(row.get(field)) for field in AXES):
            return "partial_auto"
        return "complete_auto"
    return "other"


def counts(rows):
    values = Counter(bucket(row) for row in rows)
    return {name: values[name] for name in BUCKETS}


def is_promotion(before, after):
    old, new = bucket(before), bucket(after)
    return new in {"complete_auto", "partial_auto"} and (
        old not in {"complete_auto", "partial_auto", "manual", "nonfault"}
        or old == "partial_auto"
        and new == "complete_auto"
    )


def keyed(rows, label):
    result = {}
    for row in rows:
        key = row.get("event_id")
        if not key or key in result:
            raise ValueError(f"{label}: event_id must be populated and unique: {key!r}")
        result[key] = row
    return result


def preservation_checks(before, after, before_summary=None, after_summary=None):
    old, new = keyed(before, "before"), keyed(after, "after")
    same_keys = old.keys() == new.keys()
    common = old.keys() & new.keys()
    immutable = (
        "record_id",
        "source_row",
        "source_sheet",
        "source_raw",
        "raw_description",
        "minutes",
    )
    changed = {
        field: [key for key in sorted(common) if old[key].get(field) != new[key].get(field)]
        for field in immutable
    }
    checks = {
        "row_count_preserved": len(before) == len(after),
        "event_id_set_preserved": same_keys,
        "immutable_fields_preserved": not any(changed.values()),
        "minutes_total_preserved": math.isclose(
            sum(float(row.get("minutes") or 0) for row in before),
            sum(float(row.get("minutes") or 0) for row in after),
            abs_tol=1e-8,
        ),
    }
    for label, summary in (("before", before_summary), ("after", after_summary)):
        if summary is None:
            continue
        if not summary.get("checks"):
            checks[f"{label}_audit_checks_present"] = False
        else:
            checks[f"{label}_audit_checks_pass"] = all(summary["checks"].values())
        a, b = summary.get("source_sha256_before"), summary.get("source_sha256_after")
        checks[f"{label}_source_bytes_unchanged"] = bool(a and b and a == b)
    if before_summary is not None and after_summary is not None:
        checks["same_source_sha256"] = bool(
            before_summary.get("source_sha256_before")
            and before_summary.get("source_sha256_before")
            == after_summary.get("source_sha256_before")
        )
    return checks, {field: ids for field, ids in changed.items() if ids}


def evidence_screen(row):
    """Retain literal support and risky passages for human semantic inspection."""
    raw = "\n".join(
        str(row.get(key) or "") for key in ("raw_description", "raw_cause", "raw_action")
    )
    raw_key, normalized_key = compact(raw), compact(row.get("normalized"))
    components = array(row.get("component_details"))
    symptom_checks = []
    for item in components:
        value = str(item.get("symptom_evidence") or "")
        tokens = [token.strip() for token in re.split(r"[,|;]", value) if token.strip()]
        symptom_checks.append(
            {
                "part": item.get("middle", ""),
                "symptom": item.get("minor", ""),
                "recorded_evidence": value,
                "tokens": [
                    {
                        "token": token,
                        "in_raw": compact(token) in raw_key,
                        "in_normalized": compact(token) in normalized_key,
                    }
                    for token in tokens
                ],
            }
        )
    action_mentions = []
    for name, pattern in ACTION_WORDS.items():
        for match in re.finditer(pattern, raw, re.I):
            context = raw[max(0, match.start() - 24) : match.end() + 30]
            action_mentions.append(
                {
                    "action": name,
                    "literal": match.group(),
                    "context": context,
                    "has_risk_word_nearby": bool(RISK_WORDS.search(compact(context))),
                }
            )
    risk_passages = [raw[max(0, m.start() - 30) : m.end() + 35] for m in RISK_WORDS.finditer(raw)]
    unsupported_tokens = [
        token["token"]
        for item in symptom_checks
        for token in item["tokens"]
        if not token["in_raw"] and not token["in_normalized"]
    ]
    explicit_failure = bool(FALLBACK_FAILURE.search(raw))
    literal_symptom = any(
        token["in_raw"] or token["in_normalized"]
        for item in symptom_checks
        for token in item["tokens"]
    )
    safe_actions = [item for item in action_mentions if not item["has_risk_word_nearby"]]
    flags = []
    if unsupported_tokens:
        flags.append("symptom_evidence_token_absent_from_raw_and_normalized")
    if not literal_symptom and not explicit_failure and not safe_actions:
        flags.append("no_literal_failure_or_unqualified_action_found")
    if risk_passages:
        flags.append("planned_normal_negated_or_uncertain_passage_needs_scope_check")
    if not unknown(row.get("minor")) and not literal_symptom:
        flags.append("named_symptom_without_component_literal_evidence")
    # A canonical label may be a legitimate synonym. Preserve it as a specific
    # alias-check item instead of treating non-literal canonical wording as false.
    part = str(row.get("middle") or "")
    bare_part = re.sub(r"\([^)]*미상[^)]*\)", "", part)
    if not unknown(part) and compact(bare_part) not in raw_key:
        flags.append("canonical_part_requires_alias_or_normalization_check")
    return {
        "screen_is_accuracy_measure": False,
        "support_kinds_seen": [
            name
            for name, present in (
                ("selected_component_F_literal", literal_symptom),
                ("failure_word_elsewhere_in_raw", explicit_failure),
                ("action_without_local_risk_word", bool(safe_actions)),
            )
            if present
        ],
        "symptom_evidence_checks": symptom_checks,
        "explicit_failure_word_seen": explicit_failure,
        "action_mentions": action_mentions,
        "risk_passages": risk_passages,
        "flags": flags,
        "interpretation": "문자열·주변 표현 확인용. 고장 부품과 조치의 의미적 연결 또는 정답을 인증하지 않음.",
    }


def comparison(before, after, before_summary=None, after_summary=None):
    checks, immutable_changes = preservation_checks(before, after, before_summary, after_summary)
    if not all(checks.values()):
        raise ValueError(
            json.dumps(
                {"preservation_checks": checks, "immutable_changes": immutable_changes},
                ensure_ascii=False,
            )
        )
    old, new = keyed(before, "before"), keyed(after, "after")
    transitions = Counter()
    changes, promotions = [], []
    for key in old:
        a, b = old[key], new[key]
        transitions[(bucket(a), bucket(b))] += 1
        # Newly introduced empty annotation fields are not a decision change.
        fields = [field for field in COMPARE_FIELDS if a.get(field, "") != b.get(field, "")]
        if not fields:
            continue
        item = {
            "event_id": key,
            "source_row": a.get("source_row"),
            "record_id": a.get("record_id"),
            "before_bucket": bucket(a),
            "after_bucket": bucket(b),
            "changed_fields": fields,
            "is_promotion": is_promotion(a, b),
            "before_known_axes": known_axes(a),
            "after_known_axes": known_axes(b),
            "axis_changes": [
                {
                    "field": field,
                    "before": a.get(field, ""),
                    "after": b.get(field, ""),
                    "was_known": not unknown(a.get(field)),
                    "is_known": not unknown(b.get(field)),
                }
                for field in AXES
                if a.get(field) != b.get(field)
            ],
            "evidence_screen": evidence_screen(b),
            "before_record": a,
            "after_record": b,
        }
        changes.append(item)
        if item["is_promotion"]:
            promotions.append(item)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows": len(before),
        "before_buckets": counts(before),
        "after_buckets": counts(after),
        "before_original_status_counts": dict(Counter(row.get("status", "") for row in before)),
        "after_original_status_counts": dict(Counter(row.get("status", "") for row in after)),
        "transitions": [
            {"before": a, "after": b, "rows": count}
            for (a, b), count in sorted(transitions.items())
        ],
        "changed_rows": len(changes),
        "promoted_rows": len(promotions),
        "promotion_screen_flag_counts": dict(
            Counter(flag for row in promotions for flag in row["evidence_screen"]["flags"])
        ),
        "checks": checks,
        "audit_provenance": {
            label: {
                "provenance": value.get("provenance", "original_audit_summary"),
                "is_original_audit_summary": value.get("is_original_audit_summary", True),
                "limitation": value.get("limitation", ""),
            }
            for label, value in (("before", before_summary), ("after", after_summary))
            if value is not None
        },
        "definitions": {
            "complete_auto": "status=규칙분류이며 4축에 미기재 값이 없음. 원문 정답 검증을 뜻하지 않음.",
            "partial_auto": "status=부분분류 또는 기존 규칙분류 중 4축에 미기재 값이 남은 행.",
            "promotion": "검토/미일치 등에서 자동/부분 자동으로 전환 또는 부분 자동에서 완전 자동으로 전환.",
            "review": "검토필요 상태만. 부분 분류와 미일치·코드 미기입은 별도 집계.",
            "baseline_reinterpretation": "기존 규칙분류도 같은 4축 완성도 기준으로 완전/부분을 분리함.",
        },
        "limitations": "정답 라벨을 갖춘 독립 실제 이력 검수셋이 없으므로 정확도 향상 수치를 산출하지 않음. 문자열 근거 검사는 의미적 연결의 정답 판정이 아님.",
    }
    return summary, changes, promotions


def md_text(value):
    return str(value or "").replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def axis_text(row):
    return " / ".join(str(row.get(field) or "(미확정)") for field in AXES)


def markdown(summary, promotions, title):
    lines = [
        f"# {title}",
        "",
        "분류 범위·검토 부담 비교입니다. 실제 정답 정확도 측정 결과가 아닙니다.",
        "",
        "기존 규칙분류도 동일한 4축 완성도 기준으로 다시 나눴습니다.",
        "",
        "| 구분 | 이전 | 이후 | 증감 |",
        "|---|---:|---:|---:|",
    ]
    for name in BUCKETS:
        a, b = summary["before_buckets"][name], summary["after_buckets"][name]
        lines.append(f"| {BUCKET_LABELS[name]} | {a} | {b} | {b - a:+d} |")
    lines.extend(
        [
            "",
            f"변경 {summary['changed_rows']}행, 자동 처리 승격 {summary['promoted_rows']}행.",
            "",
            "원문·행·식별자·정지시간 보존 검사: "
            + ("통과" if all(summary["checks"].values()) else "실패"),
            "",
            "## 상태 이동",
            "",
            "| 이전 | 이후 | 건수 |",
            "|---|---|---:|",
        ]
    )
    for item in summary["transitions"]:
        lines.append(
            f"| {BUCKET_LABELS[item['before']]} | {BUCKET_LABELS[item['after']]} | {item['rows']} |"
        )
    lines.extend(
        [
            "",
            "## 모든 승격 행의 원문과 근거",
            "",
            "아래 점검 표시는 검수 대상을 찾는 문자열 검사입니다. 정상·예정·부정·추정 표현이 같은 기록에 있으면 해당 부품과의 연결을 확인해야 합니다. 별칭 표시는 동의어 사전과 대조해야 합니다. 전체 원본 필드·후보·추적 결과는 promotions.json에 보존했습니다.",
        ]
    )
    for item in promotions:
        a, b = item["before_record"], item["after_record"]
        lines.extend(
            [
                "",
                f"### 원본 {item['source_row']}행 — {BUCKET_LABELS[item['before_bucket']]} → {BUCKET_LABELS[item['after_bucket']]}",
                "",
                f"- 이벤트: `{item['event_id']}`",
                f"- 원문: {md_text(b.get('raw_description'))}",
                f"- 이전: {md_text(axis_text(a))}",
                f"- 이후: {md_text(axis_text(b))}",
                f"- 조치: {md_text(b.get('repair_actions')) or '(없음)'}",
                f"- 판정 사유: {md_text(b.get('classification_reason'))}",
                f"- 선택 근거: {md_text(b.get('evidence'))}",
                f"- 확인 표시: {', '.join(item['evidence_screen']['flags']) or '(문자열 검사에서 별도 표시 없음)'}",
            ]
        )
        for label, row in (("이전 후보", a), ("이후 후보", b)):
            candidates = array(row.get("classification_candidates"))
            lines.append(
                f"- {label}: "
                + (
                    "; ".join(
                        md_text(axis_text(c)) + " [" + md_text(c.get("evidence")) + "]"
                        for c in candidates
                    )
                    or "(없음)"
                )
            )
    lines.extend(["", "## 해석 범위", "", summary["limitations"], ""])
    for label, provenance in summary.get("audit_provenance", {}).items():
        if not provenance["is_original_audit_summary"]:
            lines.extend(
                [f"감사 증빙 ({label}): {provenance['provenance']}. {provenance['limitation']}", ""]
            )
    return "\n".join(lines)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def summary_path(records):
    return records.with_name(records.stem.removesuffix("_records") + "_summary.json")


def output_paths(directory, run_name):
    """Audit and comparison artifacts must have distinct filenames."""
    return {
        suffix: directory / f"{run_name}_comparison_{suffix}.{extension}"
        for suffix, extension in (
            ("summary", "json"),
            ("changes", "json"),
            ("promotions", "json"),
            ("review", "md"),
        )
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--before",
        type=Path,
        default=ROOT / "output/review_rate_2026_20261112/baseline_v1_13_0_records.json",
    )
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--before-summary", type=Path)
    parser.add_argument("--after-summary", type=Path)
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "output/review_improvement_v114_20261112"
    )
    parser.add_argument("--run-name", default="stage_comparison")
    args = parser.parse_args()
    if not re.fullmatch(r"[\w.-]+", args.run_name):
        parser.error("--run-name must be a filename component")
    old_summary = args.before_summary or summary_path(args.before)
    new_summary = args.after_summary or summary_path(args.after)
    outputs = output_paths(args.output_dir, args.run_name)
    inputs = {path.resolve() for path in (args.before, args.after, old_summary, new_summary)}
    if any(path.resolve() in inputs for path in outputs.values()):
        parser.error("comparison output cannot overwrite any audit input")
    # The CLI requires full audit summaries so code/source integrity checks are
    # not silently omitted. Unit callers may compare self-contained toy rows.
    summary, changes, promotions = comparison(
        read_json(args.before),
        read_json(args.after),
        read_json(old_summary),
        read_json(new_summary),
    )
    summary["input_artifacts"] = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (args.before, args.after, old_summary, new_summary)
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for suffix, value in (("summary", summary), ("changes", changes), ("promotions", promotions)):
        outputs[suffix].write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    outputs["review"].write_text(markdown(summary, promotions, args.run_name), encoding="utf-8")
    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "rows",
                    "before_buckets",
                    "after_buckets",
                    "changed_rows",
                    "promoted_rows",
                    "promotion_screen_flag_counts",
                    "checks",
                )
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
