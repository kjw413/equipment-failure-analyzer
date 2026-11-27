"use client";

import { Activity, ArrowDownRight, ArrowRight, ArrowUpRight, Clock3, Gauge, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { DataGrid, Empty, useApi, type Filter } from "./data-grid";
import { comparisonFields, display, params, type Analysis, type Comparison, type ComparisonField, type RecordRow, type Table } from "./lib";

const metrics = [
  { key: "selected_rows", label: "분석 기록", unit: "건", icon: Activity },
  { key: "total_minutes", label: "정지시간", unit: "분", icon: Clock3 },
  { key: "equipment_count", label: "설비 수", unit: "대", icon: Gauge },
  { key: "review_rows", label: "검토 필요", unit: "건", icon: TriangleAlert },
];

export function Metrics({ analysis }: { analysis: Analysis }) {
  return <><div className="metric-grid">
    {metrics.map(({ key, label, icon: Icon, unit }) => <div key={key} className="card metric">
      <span><Icon size={17} /> {label}</span>
      <strong>{display(analysis.metrics[key])} <small>{unit}</small></strong>
    </div>)}
  </div>
    <dl className="metric-details">
      <div><dt>평균 정지시간</dt><dd>{analysis.metrics.mean_minutes == null ? "—" : `${display(analysis.metrics.mean_minutes)}분`}</dd></div>
      <div><dt>완전분류</dt><dd>{display(analysis.metrics.auto_rows)}건</dd></div>
      <div><dt>부분분류</dt><dd>{display(analysis.metrics.partial_rows)}건</dd></div>
    </dl>
  </>;
}

type Metric = "count" | "total_minutes";
type ChartOption = { key: string; label: string; field: string };
const breakdowns: ChartOption[] = [
  { key: "line", label: "라인별", field: "line" },
  { key: "factory", label: "공장별", field: "factory" },
  { key: "team", label: "팀별", field: "team" },
  { key: "equipment", label: "설비별", field: "equipment" },
  { key: "detailed_equipment", label: "상세설비별", field: "detail_equipment" },
  { key: "type", label: "고장유형별", field: "type" },
  { key: "equipment_types", label: "설비별 고장유형", field: "type" },
];
const periods: ChartOption[] = [
  { key: "trend_month", label: "월별", field: "period" },
  { key: "trend_day", label: "일별", field: "period" },
  { key: "trend_week", label: "주별", field: "period" },
  { key: "trend_year", label: "연별", field: "period" },
];
const periodKeys = new Set(periods.map((item) => item.key));
const chartOptions = [...breakdowns, ...periods];

function historyFilter(key: string, field: string, row: RecordRow): Filter | undefined {
  if (row[field] == null) return;
  const secondaryFields: Record<string, string> = {
    detailed_equipment: "line",
    equipment_types: "equipment",
    team: "factory",
  };
  const secondField = secondaryFields[key];
  return {
    field,
    value: String(row[field]),
    also: secondField && row[secondField] != null
      ? { field: secondField, value: String(row[secondField]) }
      : undefined,
  };
}

export function ChartPanel({
  mode, analysis, revision, onHistory,
}: {
  mode: "overview" | "trend";
  analysis: Analysis;
  revision: number;
  onHistory: (filter: Filter) => void;
}) {
  const [selected, setSelected] = useState(mode === "trend" ? "trend_month" : "line");
  const [metric, setMetric] = useState<Metric>("total_minutes");
  const [equipment, setEquipment] = useState("");
  const [month, setMonth] = useState("");
  const choices = (mode === "trend" ? periods : breakdowns).filter((item) => analysis.tables.some(({ key }) => key === item.key));
  const active = choices.find(({ key }) => key === selected) ?? choices[0];
  const timeline = active && periodKeys.has(active.key);
  const filter = active?.key === "equipment_types" && equipment ? { field: "equipment", value: equipment } : undefined;
  const query = active?.key === "trend_day" ? month : "";
  const filteredEquipments = useApi<Table>(active?.key === "equipment_types" ? "/table/equipment?limit=200" : null, revision);
  const months = useApi<Table>(mode === "trend" ? "/table/trend_month?limit=200" : null, revision);
  const chart = useApi<Table>(active ? `/table/${active.key}${params({
    limit: timeline ? 60 : analysis.options.top_n,
    q: query,
    sort: timeline ? "period" : metric,
    order: timeline ? "asc" : "desc",
    filter_field: filter?.field,
    filter_value: filter?.value,
  })}` : null, revision);
  const rows = chart.data?.rows ?? [];
  const maximum = Math.max(1, ...rows.map((row) => Number(row[metric]) || 0));

  function clickBar(row: RecordRow) {
    if (!active || row[active.field] == null) return;
    const value = String(row[active.field]);
    if (active.key === "trend_month") {
      setMonth(value);
      setSelected("trend_day");
    } else if (!timeline) {
      const drilled = historyFilter(active.key, active.field, row);
      if (drilled) onHistory(drilled);
    }
  }

  return <section className="card chart-card">
    <div className="section-heading">
      <div><h2>{mode === "trend" ? "기간별 실적" : "주요 고장 현황"}</h2></div>
      <div className="toolbar">
        <select aria-label="차트 집계 기준" value={active?.key ?? ""} onChange={(event) => setSelected(event.target.value)}>
          {choices.map(({ key, label }) => <option value={key} key={key}>{label}</option>)}
        </select>
        <select aria-label="차트 지표" value={metric} onChange={(event) => setMetric(event.target.value as Metric)}>
          <option value="total_minutes">정지시간</option><option value="count">건수</option>
        </select>
        {active?.key === "equipment_types" && <select aria-label="설비 선택" value={equipment} onChange={(event) => setEquipment(event.target.value)}>
          <option value="">모든 설비</option>
          {filteredEquipments.data?.rows.map((row) => <option key={String(row.equipment)} value={String(row.equipment)}>{display(row.equipment)}</option>)}
        </select>}
        {active?.key === "trend_day" && <select aria-label="월 선택" value={month} onChange={(event) => setMonth(event.target.value)}>
          <option value="">모든 월</option>
          {months.data?.rows.map((row) => <option key={String(row.period)} value={String(row.period)}>{display(row.period)}</option>)}
        </select>}
      </div>
    </div>
    {chart.error && <div role="alert" className="notice error">{chart.error}</div>}
    {chart.loading && <Empty><span role="status">차트를 불러오는 중…</span></Empty>}
    {!chart.loading && !chart.error && !rows.length && <Empty>표시할 집계가 없습니다.</Empty>}
    {!!rows.length && active && <div className="bars" aria-label={`${active.label} ${metric === "count" ? "건수" : "정지시간"} 차트`}>
      {rows.map((row, index) => {
        const drill = historyFilter(active.key, active.field, row);
        const name = drill?.also ? `${drill.also.value} · ${drill.value}` : display(row[active.field]);
        const number = Number(row[metric]) || 0;
        const clickable = !timeline || active.key === "trend_month";
        const content = <>
          <span className="bar-label">{name}</span>
          <span className="bar-track"><span className="bar-fill" style={{ width: `${Math.max(0, number / maximum) * 100}%` }} /></span>
          <span className="bar-value">{display(number)}{metric === "count" ? "건" : "분"}</span>
          {clickable && <ArrowRight className="bar-action" size={15} aria-hidden />}
        </>;
        return clickable
          ? <button className="bar-row" key={`${name}/${index}`} onClick={() => clickBar(row)}>{content}</button>
          : <div className="bar-row" key={`${name}/${index}`}>{content}</div>;
      })}
    </div>}
    {mode === "trend" && active && <DataGrid key={`${active.key}/${query}`} tableKey={active.key} revision={revision} query={query}
      onDrill={active.key === "trend_month" ? clickBar : undefined} drillLabel="일별 보기" />}
  </section>;
}

export function BreakdownTables({
  analysis, revision, onHistory, onOpen,
}: {
  analysis: Analysis;
  revision: number;
  onHistory: (filter: Filter) => void;
  onOpen: (row: RecordRow) => void;
}) {
  const [selected, setSelected] = useState("line");
  const options = analysis.tables.filter(({ key }) => !["raw", "detail", "review"].includes(key) && !periodKeys.has(key));
  const active = options.find(({ key }) => key === selected) ?? options[0];
  const field = chartOptions.find(({ key }) => key === active?.key)?.field;
  return <section className="card">
    <div className="section-heading">
      <div><h2>집계표</h2><p>설비, 라인, 고장유형과 제품 교차분석을 확인합니다.</p></div>
      <select aria-label="집계표 선택" value={active?.key ?? ""} onChange={(event) => setSelected(event.target.value)}>
        {options.map(({ key, label }) => <option key={key} value={key}>{label}</option>)}
      </select>
    </div>
    {active ? <DataGrid key={active.key} tableKey={active.key} revision={revision} onOpen={active.key === "long_stops" ? onOpen : undefined}
      onDrill={field ? (row) => { const drilled = historyFilter(active.key, field, row); if (drilled) onHistory(drilled); } : undefined} />
      : <Empty>표시할 집계가 없습니다.</Empty>}
  </section>;
}

const comparisonLabels: Record<string, string> = {
  ...comparisonFields,
  equipment: "설비",
  detail_equipment: "상세설비",
  count: "건수",
  total_minutes: "정지시간 (분)",
  label: "항목",
  key: "항목",
  name: "이름",
};

function ComparisonTable({ rows }: { rows: RecordRow[] }) {
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  return <div className="table-scroll" tabIndex={0}>
    <table>
      <thead><tr>{columns.map((key) => <th key={key}>{comparisonLabels[key] ?? key}</th>)}</tr></thead>
      <tbody>{rows.map((row, index) => <tr key={index}>{columns.map((key) => <td className={typeof row[key] === "number" ? "numeric" : undefined} key={key}>{display(row[key])}</td>)}</tr>)}</tbody>
    </table>
    {!rows.length && <Empty>조건에 맞는 기록이 없습니다.</Empty>}
  </div>;
}

export function ComparisonPanel({ revision }: { revision: number }) {
  const [base, setBase] = useState<Partial<Record<ComparisonField, string>>>({});
  const [compared, setCompared] = useState<Partial<Record<ComparisonField, string>>>({});
  const fields = Object.entries(comparisonFields) as [ComparisonField, string][];
  const query = params(Object.fromEntries(fields.flatMap(([key]) => [[`base_${key}`, base[key]], [`compare_${key}`, compared[key]]])));
  const defaults = useApi<Comparison>("/comparison", revision);
  const filtered = useApi<Comparison>(query ? `/comparison${query}` : null, revision);
  const current = query ? filtered : defaults;
  const data = current.data;
  const choices = data?.choices ?? defaults.data?.choices;
  const countChange = data ? data.comparison.count - data.base.count : 0;
  const minutesChange = data?.comparison.total_minutes != null && data.base.total_minutes != null
    ? data.comparison.total_minutes - data.base.total_minutes : null;

  return <section className="card">
    <div className="section-heading"><div><h2>고장 비교</h2><p>양쪽에 해당하는 이력은 기준에만 집계됩니다.</p></div></div>
    <div className="compare-grid">
      {([
        { label: "기준", selection: base, update: setBase, result: data?.base },
        { label: "비교 대상", selection: compared, update: setCompared, result: data?.comparison },
      ]).map(({ label, selection, update, result }) => <div className="compare-panel" key={label}>
        <div className="section-heading"><h3>{label}</h3>
          <button className="button plain" onClick={() => update({})}>초기화</button>
        </div>
        <div className="form-grid">
          {fields.map(([key, caption]) => <label key={key}>{caption}
            <select value={selection[key] ?? ""} onChange={(event) => update((previous) => ({ ...previous, [key]: event.target.value }))}>
              <option value="">전체</option>
              {(choices?.[key] ?? []).map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>)}
        </div>
        {result && <>
          <div className="compare-stat"><strong>{display(result.count)}건</strong><strong>{result.total_minutes == null ? "정지시간 미기재" : `${display(result.total_minutes)}분`}</strong></div>
          <ComparisonTable rows={result.rows} />
          {result.group_count > result.rows.length && <p className="muted">전체 {display(result.group_count)}개 그룹 중 상위 {display(result.rows.length)}개 표시</p>}
        </>}
      </div>)}
    </div>
    {current.loading && <Empty><span role="status">비교 결과를 불러오는 중…</span></Empty>}
    {current.error && <div role="alert" className="notice error">{current.error}</div>}
    {data && <div className="compare-delta">{(minutesChange ?? countChange) > 0 ? <ArrowUpRight size={18} /> : <ArrowDownRight size={18} />} 차이
      <strong>{countChange > 0 && "+"}{display(countChange)}건</strong>
      {minutesChange != null && <strong>{minutesChange > 0 && "+"}{display(minutesChange)}분</strong>}</div>}
  </section>;
}
