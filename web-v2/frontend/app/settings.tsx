"use client";

import { Download, Plus, Save, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { Empty } from "./data-grid";
import { display, type Scalar, type Settings } from "./lib";

type SaveSettings = (section: string, fields: unknown, method?: string) => void;
type NameSource = "line" | "equipment";
type NameRow = { id: number; code: string; raw: string; name: string; group: string; factory: string; team: string };

export function ReportPanel({
  settings, canExport, busy, pendingCount, stale, onSave, onDownload,
}: {
  settings?: Settings;
  canExport: boolean;
  busy: boolean;
  pendingCount: number;
  stale: boolean;
  onSave: SaveSettings;
  onDownload: (format: "xlsx" | "xlsm") => void;
}) {
  const original = String(settings?.report.department ?? "");
  const [department, setDepartment] = useState(original);
  const [format, setFormat] = useState<"xlsx" | "xlsm">("xlsm");
  return <>
    <section className="card">
      <div className="section-heading"><div><h2>Excel 보고서</h2><p>종합현황, 팀별·월별 실적, 고장 비교와 검토 이력을 내려받습니다.</p></div></div>
      {pendingCount > 0 && <div className="notice warning">확정 대기 분류 {display(pendingCount)}건이 있습니다. 검수 화면에서 적용한 뒤 보고서를 생성하세요.</div>}
      {stale && <div className="notice warning">보고서를 생성하기 전에 변경한 조건으로 재분석합니다.</div>}
      <div className="form-row">
        <label>파일 형식<select value={format} onChange={(event) => setFormat(event.target.value as "xlsx" | "xlsm")}>
          <option value="xlsm">Excel 매크로 포함 (.xlsm)</option><option value="xlsx">Excel 통합 문서 (.xlsx)</option>
        </select></label>
        <button className="button primary" disabled={!canExport || busy} onClick={() => onDownload(format)}><Download size={17} /> 보고서 다운로드</button>
      </div>
    </section>
    <section className="card">
      <div className="section-heading"><div><h2>보고서 옵션</h2></div></div>
      <form className="form-row" onSubmit={(event) => { event.preventDefault(); onSave("report", { department }); }}>
        <label>부서<input value={department} onChange={(event) => setDepartment(event.target.value)} maxLength={120} /></label>
        <button className="button secondary" disabled={busy || !settings || department === original}><Save size={16} /> 저장</button>
      </form>
    </section>
  </>;
}

function ReviewColors({ settings, busy, onSave }: { settings: Settings; busy: boolean; onSave: SaveSettings }) {
  const [colors, setColors] = useState(settings.review_colors);
  const defaults = Object.fromEntries(settings.review_color_types.map(({ key, default: value }) => [key, value]));
  return <section className="card">
    <div className="section-heading"><div><h2>검토 필요 색상</h2><p>검토 사유별로 사용할 강조 색상을 지정합니다.</p></div></div>
    <form onSubmit={(event) => { event.preventDefault(); onSave("review-colors", colors); }}>
      <div className="form-grid">
        {settings.review_color_types.map(({ key, label, default: value }) => <label key={key}>{label}
          <span className="color-control"><input type="color" value={colors[key] ?? value} onChange={(event) => setColors({ ...colors, [key]: event.target.value.toUpperCase() })} />
            <code>{colors[key] ?? value}</code></span>
        </label>)}
      </div>
      <div className="action-row">
        <button className="button plain" type="button" disabled={busy} onClick={() => setColors(defaults)}>기본 색상으로</button>
        <button className="button primary" disabled={busy}><Save size={16} /> 색상 저장</button>
      </div>
    </form>
  </section>;
}

function nameRows(settings: Settings, source: NameSource): NameRow[] {
  const saved = settings.equipment_names;
  const mapping = (source === "line" ? saved.line_mappings : saved.mappings) ?? {};
  const organization = saved.organization?.[source] ?? {};
  const overrides = saved.grouping?.overrides ?? {};
  const raw = Object.fromEntries(settings.equipment_catalog[source].map((item) => [item.code, item.raw_name]));
  const codes = [...new Set([...Object.keys(raw), ...Object.keys(mapping), ...Object.keys(organization)])].sort((a, b) => a.localeCompare(b, "ko"));
  return codes.map((code, id) => ({
    id, code, raw: raw[code] ?? "", name: mapping[code] ?? "",
    group: overrides[mapping[code] || (source === "line" ? raw[code] : code) || code] ?? "",
    factory: organization[code]?.factory ?? "", team: organization[code]?.team ?? "",
  }));
}
const nameFields = { code: "코드", name: "변환 명칭", group: "그룹", factory: "공장", team: "팀" } as const;

function EquipmentNames({ settings, busy, onSave }: { settings: Settings; busy: boolean; onSave: SaveSettings }) {
  const [source, setSource] = useState<NameSource>(settings.equipment_names.source);
  const [catalog, setCatalog] = useState(() => ({ line: nameRows(settings, "line"), equipment: nameRows(settings, "equipment") }));
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");
  const [groupMode, setGroupMode] = useState(settings.equipment_names.grouping?.mode ?? "prefix");
  const [separator, setSeparator] = useState(settings.equipment_names.grouping?.separator ?? "#");
  const rows = catalog[source];
  const visible = rows.filter((row) => Object.values(row).some((value) => String(value).toLowerCase().includes(query.trim().toLowerCase())));
  const activePage = Math.min(page, Math.max(0, Math.ceil(visible.length / 25) - 1));
  const originalGrouping = settings.equipment_names.grouping;

  function save() {
    if (groupMode === "prefix" && !separator.trim()) {
      setError("자동 그룹에 사용할 구분자를 입력하세요.");
      return;
    }
    const filled = rows.filter((row) => [row.code, row.name, row.group, row.factory, row.team].some((value) => value.trim()));
    const codes = filled.map(({ code }) => code.trim().toUpperCase());
    if (codes.includes("") || new Set(codes).size !== codes.length) {
      setError("코드를 입력하고 중복된 코드가 없는지 확인하세요.");
      return;
    }
    setError("");
    const mapping = Object.fromEntries(filled.filter(({ name }) => name.trim()).map(({ code, name }) => [code.trim(), name.trim()]));
    const organization = Object.fromEntries(filled.filter(({ factory, team }) => factory.trim() || team.trim()).map(({ code, factory, team }) => [code.trim(), { factory: factory.trim(), team: team.trim() }]));
    const overrides = { ...originalGrouping?.overrides };
    const reportName = (row: NameRow) => row.name.trim() || (source === "line" ? row.raw : row.code.trim()) || row.code.trim();
    for (const row of nameRows(settings, source)) delete overrides[reportName(row)];
    for (const row of filled) {
      if (row.group.trim()) overrides[reportName(row)] = row.group.trim();
    }
    onSave("equipment-names", { source, mapping, grouping: { mode: groupMode, separator, overrides }, organization: { [source]: organization } });
  }

  return <section className="card">
    <div className="section-heading"><div><h2>설비 · 라인 명칭</h2><p>코드별 표시 이름, 그룹과 소속을 관리합니다.</p></div>
      <button className="button primary" disabled={busy} onClick={save}><Save size={16} /> 명칭 저장</button>
    </div>
    {error && <div className="notice error" role="alert">{error}</div>}
    <div className="form-row name-grouping">
      <label>자동 그룹 방식<select value={groupMode} onChange={(event) => setGroupMode(event.target.value)}>
        <option value="prefix">구분자 앞부분으로 그룹 지정</option><option value="none">표시 이름으로 그룹 지정</option>
      </select></label>
      <label className="short-field">구분자<input value={separator} disabled={groupMode !== "prefix" || busy}
        maxLength={30} onChange={(event) => setSeparator(event.target.value)} /></label>
    </div>
    <div className="toolbar">
      <select aria-label="명칭 변환 기준" value={source} onChange={(event) => { setSource(event.target.value as NameSource); setPage(0); setQuery(""); }}>
        <option value="line">라인 코드 기준</option><option value="equipment">설비 코드 기준</option>
      </select>
      <label className="search"><Search size={17} aria-hidden /><input value={query} aria-label="설비 코드 및 명칭 검색" placeholder="코드 또는 이름 검색" onChange={(event) => { setPage(0); setQuery(event.target.value); }} /></label>
      <button className="button secondary" disabled={busy} onClick={() => {
        const id = rows.reduce((maximum, row) => Math.max(maximum, row.id), -1) + 1;
        setCatalog({ ...catalog, [source]: [{ id, code: "", raw: "", name: "", group: "", factory: "", team: "" }, ...rows] });
        setPage(0);
        setQuery("");
      }}><Plus size={16} /> 추가</button>
    </div>
    <div className="table-scroll input-table" tabIndex={0}>
      <table>
        <thead><tr><th>원본 명칭</th>{Object.values(nameFields).map((label) => <th key={label}>{label}</th>)}<th>작업</th></tr></thead>
        <tbody>{visible.slice(activePage * 25, (activePage + 1) * 25).map((row) => <tr key={row.id}>
          <td>{display(row.raw)}</td>
          {(Object.entries(nameFields) as [keyof typeof nameFields, string][]).map(([key, label]) => <td key={key}>
            <input aria-label={label} value={row[key]} disabled={busy}
              placeholder={key === "factory" ? settings.organization_catalog[source]?.[row.code]?.factory || undefined : undefined}
              onChange={(event) => setCatalog({ ...catalog, [source]: rows.map((item) => item.id === row.id ? { ...item, [key]: event.target.value } : item) })} />
          </td>)}
          <td><button className="button icon" aria-label="명칭 삭제" disabled={busy} onClick={() => setCatalog({ ...catalog, [source]: rows.filter((item) => item.id !== row.id) })}><Trash2 size={16} /></button></td>
        </tr>)}</tbody>
      </table>
      {!visible.length && <Empty>표시할 명칭이 없습니다.</Empty>}
    </div>
    <div className="grid-footer"><span>{display(visible.length)}건</span><div className="pagination">
      <button className="button plain" disabled={activePage === 0} onClick={() => setPage(activePage - 1)}>이전</button>
      <button className="button plain" disabled={(activePage + 1) * 25 >= visible.length} onClick={() => setPage(activePage + 1)}>다음</button>
    </div></div>
  </section>;
}

const rulesDefault: Record<string, Scalar> = { id: "", enabled: true, priority: 100, major: "", middle: "기타", minor: "세부 부품 미기재", context: "", symptom: "", exclude: "", role: "component" };
const ruleLabels: Record<string, string> = { id: "규칙 ID", priority: "우선순위", major: "분야", context: "일치 조건", symptom: "현상 조건", exclude: "제외 조건", role: "역할" };

function Rules({ settings, busy, onSave }: { settings: Settings; busy: boolean; onSave: SaveSettings }) {
  const [rules, setRules] = useState(settings.rules);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [editor, setEditor] = useState<{ index: number; value: Record<string, Scalar> }>();
  const visible = rules.map((value, index) => ({ value, index })).filter(({ value }) => Object.values(value).some((field) => String(field ?? "").toLowerCase().includes(query.trim().toLowerCase())));
  const activePage = Math.min(page, Math.max(0, Math.ceil(visible.length / 12) - 1));
  const columns = settings.rule_columns.filter((key) => key in ruleLabels);
  return <section className="card">
    <div className="section-heading"><div><h2>분류 규칙</h2><p>규칙을 추가하거나 조건을 편집하고 변경 사항을 저장하세요.</p></div>
      <button className="button primary" disabled={busy || rules === settings.rules || !!editor} onClick={() => onSave("rules", rules, "PUT")}><Save size={16} /> 규칙 저장</button>
    </div>
    <div className="toolbar">
      <label className="search"><Search size={17} aria-hidden /><input aria-label="규칙 검색" placeholder="규칙 검색" value={query} onChange={(event) => { setQuery(event.target.value); setPage(0); }} /></label>
      <button className="button secondary" disabled={busy || !!editor} onClick={() => setEditor({ index: -1, value: rulesDefault })}><Plus size={16} /> 새 규칙</button>
    </div>
    {editor && <form className="rule-editor" onSubmit={(event) => {
      event.preventDefault();
      setRules(editor.index === -1 ? [editor.value, ...rules] : rules.map((rule, index) => index === editor.index ? editor.value : rule));
      if (editor.index === -1) { setPage(0); setQuery(""); }
      setEditor(undefined);
    }}>
      <div className="form-grid">{columns.map((key) => <label key={key}>{ruleLabels[key]}
        {key === "role" ? <select value={String(editor.value[key] ?? "component")} onChange={(event) => setEditor({ ...editor, value: { ...editor.value, [key]: event.target.value } })}>
          <option value="component">부품</option><option value="fallback">대체</option>
          <option value="override">원인 우선</option><option value="nopart">부품 없음</option>
        </select> : <input type={key === "priority" ? "number" : "text"} required={key !== "exclude"} value={String(editor.value[key] ?? "")}
          onChange={(event) => setEditor({ ...editor, value: { ...editor.value, [key]: event.target.value } })} />}
      </label>)}</div>
      <label className="checkbox"><input type="checkbox" checked={editor.value.enabled === true || editor.value.enabled === "1"} onChange={(event) => setEditor({ ...editor, value: { ...editor.value, enabled: event.target.checked } })} /> 규칙 사용</label>
      <div className="action-row"><button type="button" className="button plain" onClick={() => setEditor(undefined)}>취소</button>
        <button className="button secondary">변경 적용</button></div>
    </form>}
    <div className="table-scroll" tabIndex={0}><table>
      <thead><tr><th>규칙 ID</th><th>사용</th><th>우선순위</th><th>분야</th><th>현상 조건</th><th>작업</th></tr></thead>
      <tbody>{visible.slice(activePage * 12, (activePage + 1) * 12).map(({ value, index }) => <tr key={index}>
        {["id", "enabled", "priority", "major", "symptom"].map((key) => <td key={key}>{display(value[key])}</td>)}
        <td className="row-actions"><button className="link-button" disabled={busy || !!editor} onClick={() => setEditor({ index, value })}>편집</button>
          <button className="button icon" aria-label="규칙 삭제" disabled={busy || !!editor} onClick={() => setRules(rules.filter((_, item) => item !== index))}><Trash2 size={16} /></button></td>
      </tr>)}</tbody>
    </table>{!visible.length && <Empty>표시할 규칙이 없습니다.</Empty>}</div>
    <div className="grid-footer"><span>{display(visible.length)}건</span><div className="pagination">
      <button className="button plain" disabled={activePage === 0} onClick={() => setPage(activePage - 1)}>이전</button>
      <button className="button plain" disabled={(activePage + 1) * 12 >= visible.length} onClick={() => setPage(activePage + 1)}>다음</button>
    </div></div>
  </section>;
}

export function SettingsPanel({ settings, busy, onSave, revision }: { settings?: Settings; busy: boolean; onSave: SaveSettings; revision: number }) {
  const [selected, setSelected] = useState<"names" | "colors" | "rules">("names");
  if (!settings) return <section className="card"><Empty>설정을 불러오는 중…</Empty></section>;
  return <>
    <div className="segmented">
      <button aria-pressed={selected === "names"} onClick={() => setSelected("names")}>명칭 관리</button>
      <button aria-pressed={selected === "rules"} onClick={() => setSelected("rules")}>분류 규칙</button>
      <button aria-pressed={selected === "colors"} onClick={() => setSelected("colors")}>검토 색상</button>
    </div>
    {selected === "names" && <EquipmentNames key={revision} settings={settings} busy={busy} onSave={onSave} />}
    {selected === "rules" && <Rules key={revision} settings={settings} busy={busy} onSave={onSave} />}
    {selected === "colors" && <ReviewColors key={revision} settings={settings} busy={busy} onSave={onSave} />}
  </>;
}
