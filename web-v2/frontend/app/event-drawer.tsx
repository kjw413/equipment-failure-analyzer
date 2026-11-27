"use client";

import { FileText, Save, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Empty, useApi } from "./data-grid";
import { display, eventPath, type EventDetail, type RecordRow, type Settings } from "./lib";

const fieldNames: Record<string, string> = {
  major: "고장 분야", detail_equipment: "상세설비", minor: "고장 현상",
  normalized: "표준 고장내용", target: "고장 설비", product: "제품",
  work_date: "작업일", minutes: "정지시간 (분)", repair_actions: "조치",
  registered: "등록 설비", line: "라인", factory: "공장", team: "팀", status: "판정",
  type: "고장유형", source_row: "원본 행", classification_reason: "분류 근거",
  candidate_evidence: "후보 근거", evidence: "판정 근거", issues: "검토 사유",
  date: "작업일", raw_description: "원문", review_reason: "검토 사유",
};
const summary = ["raw_description", "source_row", "date", "minutes", "factory", "team", "line", "registered", "status", "type", "review_reason", "classification_reason", "candidate_evidence"];
const categories = ["major", "detail_equipment", "minor"] as const;
const ordinaryFields = ["normalized", "target", "product", "work_date", "minutes", "repair_actions"] as const;

function RecordFields({ data, labels = {} }: { data: RecordRow; labels?: Record<string, string> }) {
  return <dl className="record-fields">{Object.entries(data).map(([key, value]) =>
    <div key={key}><dt>{labels[key] ?? key}</dt><dd>{display(value)}</dd></div>,
  )}</dl>;
}

function EditEvent({
  detail, busy, settings, colors, onSave,
}: {
  detail: EventDetail;
  busy: boolean;
  settings?: Settings;
  colors?: Record<string, string>;
  onSave: (values: Record<string, string | null>, confirm?: boolean) => void;
}) {
  const baseline = Object.fromEntries(Object.entries({ ...detail.values, ...detail.pending }).map(([key, value]) => [key, value == null ? "" : String(value)]));
  const [values, setValues] = useState<Record<string, string>>(baseline);
  const [shown, setShown] = useState<"record" | "source">("record");
  const [selectedCandidate, setSelectedCandidate] = useState(false);
  const hasPending = !!detail.pending && Object.keys(detail.pending).length > 0;
  const patches = Object.fromEntries(Object.entries(values).filter(([key, value]) => value !== (baseline[key] ?? "")));
  const paths = settings?.classification_paths ?? [];
  const categoryOptions = [
    paths.map(([major]) => major),
    paths.filter(([major]) => !values.major || major === values.major).map((path) => path[1]),
    paths.filter(([major, equipment]) => (!values.major || major === values.major) && (!values.detail_equipment || equipment === values.detail_equipment)).map((path) => path[2]),
  ];
  const candidates = detail.candidates ?? [];
  const delta = Object.keys(patches).length;
  const confirm = selectedCandidate && categories.every((key) => values[key]?.trim());
  const reviewColor = colors?.[String(detail.record.review_color_key ?? "")];

  return <>
    <div className="segmented drawer-tabs">
      <button type="button" aria-pressed={shown === "record"} onClick={() => setShown("record")}>분류 검수</button>
      <button type="button" aria-pressed={shown === "source"} onClick={() => setShown("source")}><FileText size={16} /> 원본 행</button>
    </div>
    {shown === "source" ? (
      detail.original && Object.keys(detail.original).length ? <RecordFields data={detail.original} /> : <Empty>표시할 원본 행이 없습니다.</Empty>
    ) : <>
      {hasPending && <div className="notice warning" style={reviewColor ? { borderColor: reviewColor } : undefined}>분류 확정 대기 중입니다. 검수 화면에서 분류를 일괄 적용할 수 있습니다.</div>}
      <RecordFields labels={fieldNames} data={Object.fromEntries(summary.filter((key) => detail.record[key] != null && detail.record[key] !== "").map((key) => [
        key, key === "date" ? String(detail.record[key]).slice(0, 10) : detail.record[key],
      ]))} />
      {candidates.length > 0 && <div className="candidate-list">
        <h3>분류 후보</h3>
        {candidates.map((candidate, index) => {
          const path = Object.fromEntries(categories.map((key) => [key, typeof candidate[key] === "string" ? candidate[key] : ""]));
          const title = Object.values(path).filter(Boolean).join(" / ");
          const evidence = candidate.evidence ?? candidate.reason;
          return <button className="candidate" disabled={busy || !title} type="button" key={index}
            onClick={() => {
              setSelectedCandidate(true);
              setValues((previous) => ({ ...previous, ...path }));
            }}>
            <strong>{title || "후보 근거"}</strong>
            {evidence != null && <span>{display(evidence)}</span>}
          </button>;
        })}
      </div>}
      <form onSubmit={(event) => {
        event.preventDefault();
        if (confirm) {
          onSave({ ...patches, ...Object.fromEntries(categories.map((key) => [key, values[key]])) }, true);
        } else if (delta) {
          onSave(patches);
        }
      }}>
        <fieldset disabled={busy} className="event-fields">
          <div className="form-grid">
            {categories.map((key, index) => <label key={key}>{fieldNames[key]}
              <input list={`category-${key}`} value={values[key] ?? ""} onChange={(event) => {
                setSelectedCandidate(false);
                setValues({ ...values, [key]: event.target.value });
              }} />
              <datalist id={`category-${key}`}>
                {[...new Set(categoryOptions[index])].filter(Boolean).map((item) => <option key={item} value={item} />)}
              </datalist>
            </label>)}
          </div>
          <div className="form-grid">
            {ordinaryFields.filter((key) => key in baseline).map((key) => <label key={key} className={key === "normalized" ? "wide" : undefined}>{fieldNames[key]}
              {key === "normalized" ? <textarea rows={3} value={values[key] ?? ""} onChange={(event) => setValues({ ...values, [key]: event.target.value })} />
                : <input type={key === "work_date" ? "date" : key === "minutes" ? "number" : "text"}
                  step={key === "minutes" ? "any" : undefined} min={key === "minutes" ? 0 : undefined}
                  list={key === "repair_actions" ? "actions" : undefined}
                  value={values[key] ?? ""}
                  onChange={(event) => setValues({ ...values, [key]: event.target.value })} />}
            </label>)}
          </div>
          <datalist id="actions">{settings?.repair_actions.map((action) => <option value={action} key={action} />)}</datalist>
          <div className="action-row"><button className="button primary" disabled={!delta && !confirm}><Save size={17} /> 변경 저장</button></div>
        </fieldset>
      </form>
    </>}
  </>;
}

export function EventDrawer({
  row, revision, busy, settings, error, onClose, onSave,
}: {
  row: RecordRow;
  revision: number;
  busy: boolean;
  settings?: Settings;
  error?: string;
  onClose: () => void;
  onSave: (values: Record<string, string | null>, confirm?: boolean) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const result = useApi<EventDetail>(eventPath(row), revision);
  useEffect(() => { if (dialog.current && !dialog.current.open) dialog.current.showModal(); }, []);

  return <dialog ref={dialog} className="event-drawer" onClose={onClose} aria-labelledby="event-title">
    <div className="drawer-header"><h2 id="event-title">고장이력 상세</h2><button className="button icon" type="button" onClick={() => dialog.current?.close()} aria-label="닫기"><X size={20} /></button></div>
    <div className="drawer-content">
      {error && <div role="alert" className="notice error">{error}</div>}
      {result.loading && <Empty><span role="status">기록을 불러오는 중…</span></Empty>}
      {result.error && <div role="alert" className="notice error">{result.error}</div>}
      {result.data && <EditEvent key={revision} detail={result.data} busy={busy} settings={settings} colors={settings?.review_colors} onSave={onSave} />}
    </div>
  </dialog>;
}
