"use client";

import { ChevronDown, FileSpreadsheet, FolderOpen, Play, SlidersHorizontal, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { display, type AnalysisOptions, type Mapping, type Source } from "./lib";

function SourceSettings({
  source, busy, onSave,
}: {
  source: Source;
  busy: boolean;
  onSave: (change: { sheet?: string; header_row?: number | null; mapping?: Mapping }) => void;
}) {
  const [sheet, setSheet] = useState(source.sheet);
  const [header, setHeader] = useState(source.header_row);
  const [mapping, setMapping] = useState(source.mapping);
  const [mappingChanged, setMappingChanged] = useState(false);
  const readChanged = sheet !== source.sheet || source.header_row !== header;
  return (
    <details className="source-settings">
      <summary><SlidersHorizontal size={16} /> 파일 읽기 및 열 연결 <ChevronDown size={16} className="chevron" /></summary>
      <div className="details-body">
        <form className="form-row" onSubmit={(event) => { event.preventDefault(); onSave({ sheet, header_row: Number.isNaN(header) ? null : header }); }}>
          <label>시트<select value={sheet} onChange={(event) => { setSheet(event.target.value); setHeader(event.target.value === source.sheet ? source.header_row : Number.NaN); }}>
            {source.sheet_names.map((name) => <option key={name}>{name}</option>)}
          </select></label>
          <label className="short-field">머리글 행<input type="number" min={1} max={250000} placeholder="자동 감지" value={Number.isNaN(header) ? "" : header} onChange={(event) => setHeader(event.target.valueAsNumber)} /></label>
          <button className="button secondary" disabled={busy || !readChanged}>다시 읽기</button>
        </form>
        <form onSubmit={(event) => { event.preventDefault(); onSave({ mapping }); }}>
          <div className="form-grid">
            {Object.entries(source.fields).map(([key, title]) => <label key={key}>{title}
              <select value={mapping[key] ?? ""} onChange={(event) => {
                setMapping((previous) => ({ ...previous, [key]: event.target.value || null }));
                setMappingChanged(true);
              }}>
                <option value="">연결 안 함</option>
                {source.headers.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            </label>)}
          </div>
          <button className="button secondary" disabled={busy || !mappingChanged}>열 연결 적용</button>
        </form>
      </div>
    </details>
  );
}

export function SourcePanel({
  source, busy, onUpload, onChange, onRemove, onRaw,
}: {
  source: Source | null;
  busy: boolean;
  onUpload: (file: File) => void;
  onChange: (change: { sheet?: string; header_row?: number | null; mapping?: Mapping }) => void;
  onRemove: () => void;
  onRaw: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  return (
    <section className="card source-card">
      <div className="section-heading">
        <div><h2>고장이력 파일</h2><p>분석에 사용할 Excel 파일을 선택하세요.</p></div>
        {source && <button className="button secondary" disabled={busy} onClick={() => input.current?.click()}><FolderOpen size={17} /> 파일 변경</button>}
      </div>
      <input ref={input} type="file" accept=".xlsx,.xlsm" aria-label="고장이력 파일 선택" hidden
        onChange={(event) => {
          const file = event.currentTarget.files?.[0];
          event.currentTarget.value = "";
          if (file) onUpload(file);
        }} />
      {source ? <>
        <div className="file-row">
          <span className="file-icon"><FileSpreadsheet size={22} /></span>
          <div className="file-name"><strong>{source.name}</strong><span>{source.sheet} · {display(source.row_count)}행 {source.skipped_count > 0 && `· 제외 ${display(source.skipped_count)}행`}</span></div>
          <button className="button plain" disabled={busy} onClick={onRaw}>원본 미리보기</button>
          <button className="button plain" disabled={busy} onClick={onRemove}>닫기</button>
        </div>
        {source.warnings.length > 0 && <ul className="notice warning">{source.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
        <SourceSettings key={`${source.sheet}/${source.header_row}/${JSON.stringify(source.mapping)}`} source={source} busy={busy} onSave={onChange} />
      </> : <div className={`drop-area ${dragging ? "dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); if (!busy) setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          const file = event.dataTransfer.files[0];
          if (!busy && file) onUpload(file);
        }}>
        <span className="upload-icon"><Upload size={25} /></span>
        <strong>Excel 파일을 여기에 놓으세요</strong>
        <span className="muted">.xlsx, .xlsm · 최대 100 MB</span>
        <button className="button primary" disabled={busy} onClick={() => input.current?.click()}>파일 선택</button>
      </div>}
    </section>
  );
}

export function Conditions({
  source, options, busy, pendingCount, onChange, onRun,
}: {
  source: Source | null;
  options: AnalysisOptions;
  busy: boolean;
  pendingCount: number;
  onChange: (change: Partial<AnalysisOptions>) => void;
  onRun: () => void;
}) {
  const teams = options.factory ? source?.organizations[options.factory] ?? [] : source?.teams ?? [];
  return (
    <section className="card">
      <div className="section-heading"><div><h2>분석 조건</h2><p>공장, 팀, 기간을 고르면 해당 기록만 분석합니다.</p></div></div>
      <form onSubmit={(event) => { event.preventDefault(); onRun(); }}>
        <fieldset disabled={busy || !source} className="conditions">
          <div className="form-grid">
            <label>공장<select value={options.factory ?? ""} onChange={(event) => onChange({ factory: event.target.value || null, team: null })}>
              <option value="">모든 공장</option>
              {(source?.factories ?? []).map((item) => <option key={item}>{item}</option>)}
            </select></label>
            <label>팀<select value={options.team ?? ""} onChange={(event) => onChange({ team: event.target.value || null })}>
              <option value="">모든 팀</option>
              {teams.map((item) => <option key={item}>{item}</option>)}
            </select></label>
            <label>시작일<input type="date" value={options.date_from ?? ""} max={options.date_to ?? undefined} onChange={(event) => onChange({ date_from: event.target.value || null })} /></label>
            <label>종료일<input type="date" value={options.date_to ?? ""} min={options.date_from ?? undefined} onChange={(event) => onChange({ date_to: event.target.value || null })} /></label>
          </div>
          <details className="source-settings">
            <summary><SlidersHorizontal size={16} /> 고급 조건 <ChevronDown size={16} className="chevron" /></summary>
            <div className="details-body">
              <div className="form-grid">
                <label>대상 범위<select value={options.scope} onChange={(event) => onChange({ scope: event.target.value })}>
                  <option value="fault">고장만</option><option value="all">모든 정지</option>
                </select></label>
                <label>설비 집계 기준<select value={options.equipment_basis} onChange={(event) => onChange({ equipment_basis: event.target.value })}>
                  <option value="mapped">표준 명칭</option><option value="group">그룹</option><option value="factory">공장</option>
                  <option value="team">팀</option><option value="target">고장 설비</option><option value="registered">등록 설비</option><option value="family">설비군</option>
                </select></label>
                <label>입력 정지시간 단위<select value={options.duration_unit} onChange={(event) => onChange({ duration_unit: event.target.value })}>
                  <option value="minutes">분</option><option value="hours">시간</option><option value="seconds">초</option><option value="excel_days">Excel 날짜 (일)</option>
                </select></label>
                <label>분석 상위 항목 수<input type="number" required min={1} max={30} value={Number.isNaN(options.top_n) ? "" : options.top_n} onChange={(event) => onChange({ top_n: event.target.valueAsNumber })} /></label>
              </div>
              <label className="checkbox"><input type="checkbox" checked={options.deduplicate} onChange={(event) => onChange({ deduplicate: event.target.checked })} /> 중복 후보 제외</label>
            </div>
          </details>
          <div className="action-row"><button className="button primary"><Play size={16} /> {pendingCount ? "분류 적용 및 재분석" : "분석 실행"}</button></div>
        </fieldset>
      </form>
    </section>
  );
}
