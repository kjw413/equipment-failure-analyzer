"use client";

import { Activity, ChartNoAxesCombined, Check, ClipboardCheck, Columns3, Database, FileSpreadsheet, FolderOpen, Gauge, List, LoaderCircle, Settings2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { BreakdownTables, ChartPanel, ComparisonPanel, Metrics } from "./analytics";
import { DataGrid, Empty, type Filter } from "./data-grid";
import { EventDrawer } from "./event-drawer";
import { api, apiResponse, defaultOptions, display, eventPath, json, type Analysis, type AnalysisOptions, type Mapping, type RecordRow, type Settings, type Source } from "./lib";
import { ReportPanel, SettingsPanel } from "./settings";
import { Conditions, SourcePanel } from "./source";

const items = [
  { key: "overview", title: "분석 개요", icon: Gauge },
  { key: "breakdown", title: "집계표", icon: Columns3 },
  { key: "trend", title: "기간별 추이", icon: ChartNoAxesCombined },
  { key: "compare", title: "고장 비교", icon: Activity },
  { key: "review", title: "분류 검수", icon: ClipboardCheck },
  { key: "history", title: "고장이력", icon: List },
  { key: "raw", title: "원본 데이터", icon: Database },
  { key: "report", title: "보고서", icon: FileSpreadsheet },
  { key: "settings", title: "기준정보 · 설정", icon: Settings2 },
] as const;
type PageKey = typeof items[number]["key"];
const resultPages = new Set<PageKey>(["breakdown", "trend", "compare", "review", "history"]);
const messageFrom = (error: unknown) => error instanceof Error ? error.message : "요청을 처리하는 중 문제가 발생했습니다.";

export default function Home() {
  const [page, setPage] = useState<PageKey>("overview");
  const [source, setSource] = useState<Source | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [settings, setSettings] = useState<Settings>();
  const [options, setOptions] = useState<AnalysisOptions>(defaultOptions);
  const [revision, setRevision] = useState(0);
  const [settingsRevision, setSettingsRevision] = useState(0);
  const [filter, setFilter] = useState<Filter>();
  const [selected, setSelected] = useState<RecordRow>();
  const [booting, setBooting] = useState(true);
  const [connected, setConnected] = useState(false);
  const [task, setTask] = useState("");
  const [error, setError] = useState("");
  const [drawerError, setDrawerError] = useState("");
  const [notice, setNotice] = useState("");
  const busy = !!task || booting;
  const pendingCount = analysis?.pending_count ?? 0;
  const stale = !!analysis && (Object.keys(options) as (keyof AnalysisOptions)[]).some((key) => options[key] !== analysis.options[key]);
  const heading = items.find(({ key }) => key === page)?.title;

  const load = useCallback(async (signal?: AbortSignal) => {
    setBooting(true);
    setError("");
    try {
      const [currentSource, currentAnalysis, currentSettings] = await Promise.all([
        api<Source | null>("/source", { signal }), api<Analysis | null>("/analysis", { signal }), api<Settings>("/settings", { signal }),
      ]);
      if (signal?.aborted) return;
      setSource(currentSource);
      setAnalysis(currentAnalysis);
      setOptions(currentAnalysis?.options ?? defaultOptions);
      setSettings(currentSettings);
      setConnected(true);
    } catch (cause) {
      if (!signal?.aborted) setError(messageFrom(cause));
    } finally {
      if (!signal?.aborted) setBooting(false);
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  function navigate(next: PageKey, selectedFilter?: Filter) {
    setPage(next);
    setFilter(selectedFilter);
    window.scrollTo(0, 0);
  }

  async function perform(label: string, operation: () => Promise<void>, inDrawer = false) {
    if (busy) return;
    setTask(label);
    setError("");
    setDrawerError("");
    setNotice("");
    try {
      await operation();
      setConnected(true);
    } catch (cause) {
      (inDrawer ? setDrawerError : setError)(messageFrom(cause));
    } finally {
      setTask("");
    }
  }

  function updateAnalysis(current: Analysis | null) {
    setAnalysis(current);
    setRevision((value) => value + 1);
  }

  async function replaceSource(next: Source | null) {
    setSource(next);
    setOptions(defaultOptions);
    updateAnalysis(null);
    setSelected(undefined);
    setSettings(await api<Settings>("/settings"));
    setSettingsRevision((value) => value + 1);
  }

  async function upload(file: File) {
    if (pendingCount && !window.confirm("확정 대기 분류가 있습니다. 현재 파일을 변경할까요?")) return;
    const data = new FormData();
    data.set("file", file);
    await perform("Excel 파일을 읽는 중…", async () => {
      await replaceSource(await api<Source>("/source", { method: "POST", body: data }));
      setNotice("파일을 읽었습니다.");
    });
  }

  async function changeSource(change: { sheet?: string; header_row?: number | null; mapping?: Mapping }) {
    if (pendingCount && !window.confirm("확정 대기 분류가 있습니다. 파일 읽기 설정을 변경할까요?")) return;
    await perform("파일을 다시 읽는 중…", async () => {
      const next = await api<Source>("/source", json("PATCH", change));
      const currentOptions = options;
      await replaceSource(next);
      setOptions({
        ...currentOptions,
        factory: currentOptions.factory && next.factories.includes(currentOptions.factory) ? currentOptions.factory : null,
        team: currentOptions.team && next.teams.includes(currentOptions.team) ? currentOptions.team : null,
      });
      setNotice("파일 읽기 설정을 반영했습니다.");
    });
  }

  function removeSource() {
    if (pendingCount && !window.confirm("확정 대기 분류가 있습니다. 현재 파일을 닫을까요?")) return;
    void perform("파일을 닫는 중…", async () => {
      await api("/source", { method: "DELETE" });
      await replaceSource(null);
      setNotice("파일을 닫았습니다.");
    });
  }

  function analyze(applyPending = false) {
    if (!source || !Number.isInteger(options.top_n) || options.top_n < 1 || options.top_n > 30) {
      setError("파일을 올리고 분석 상위 항목 수를 1~30 사이로 입력하세요.");
      return;
    }
    void perform(applyPending ? "분류를 적용하고 재분석하는 중…" : "고장이력을 분석하는 중…", async () => {
      const result = await api<Analysis>(applyPending ? "/standardize" : "/analysis", json("POST", options));
      updateAnalysis(result);
      setOptions(result.options);
      setNotice(applyPending ? "분류를 적용하고 재분석했습니다." : "분석이 완료되었습니다.");
    });
  }

  function saveEvent(values: Record<string, string | null>, confirm = false) {
    if (!selected) return;
    const path = eventPath(selected);
    void perform("이력 변경을 저장하는 중…", async () => {
      const result = await api<Analysis>(path, json("PATCH", { values, confirm }));
      updateAnalysis(result);
      setNotice("이력 변경을 저장했습니다.");
    }, true);
  }

  function saveSettings(section: string, fields: unknown, method = "PATCH") {
    void perform("설정을 저장하는 중…", async () => {
      const next = await api<Settings>(`/settings/${section}`, json(method, fields));
      setSettings(next);
      setSettingsRevision((value) => value + 1);
      const [currentSource, result] = await Promise.all([api<Source | null>("/source"), api<Analysis | null>("/analysis")]);
      setSource(currentSource);
      updateAnalysis(result);
      setNotice("설정을 저장했습니다.");
    });
  }

  function download(format: "xlsx" | "xlsm") {
    if (!source || !Number.isInteger(options.top_n) || options.top_n < 1 || options.top_n > 30) {
      setError("파일을 올리고 분석 상위 항목 수를 1~30 사이로 입력하세요.");
      return;
    }
    void perform("보고서를 생성하는 중…", async () => {
      if (stale || !analysis) {
        const result = await api<Analysis>("/analysis", json("POST", options));
        updateAnalysis(result);
        setOptions(result.options);
      }
      const response = await apiResponse(`/export?format=${format}`);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(await response.blob());
      link.download = /filename="?([^";]+)"?/i.exec(response.headers.get("Content-Disposition") ?? "")?.[1] ?? `Equipment_Analysis.${format}`;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
      setNotice("보고서를 다운로드했습니다.");
    });
  }

  function showHistory(next: Filter) {
    navigate("history", next);
  }

  const openEvent = (row: RecordRow) => { setDrawerError(""); setSelected(row); };

  return (
    <div className="workspace">
      <aside className="sidebar">
        <button className="brand" type="button" onClick={() => navigate("overview")} aria-label="설비 고장 분석기 홈">
          <span className="brand-icon"><Activity size={22} strokeWidth={2.2} /></span>
          <span>설비 고장 분석기<small>버전 2</small></span>
        </button>
        <nav aria-label="작업 메뉴">
          {items.map(({ key, title, icon: Icon }) => <button type="button" key={key}
            aria-current={key === page ? "page" : undefined}
            onClick={() => navigate(key)}><Icon size={18} aria-hidden /><span>{title}</span>
            {key === "review" && pendingCount > 0 && <span className="nav-count">{display(pendingCount)}</span>}
          </button>)}
        </nav>
        <div className="connection"><span className={connected ? "online-dot" : "offline-dot"} />{booting ? "연결 중" : connected ? "분석 서버 연결됨" : "분석 서버 연결 필요"}</div>
      </aside>
      <main className="main" id="main">
        <div className="page-header">
          <div>
            <h1>{heading}</h1>
            {source && <p className="page-source"><FileSpreadsheet size={16} />{source.name}</p>}
          </div>
          {analysis && page !== "report" && <button className="button secondary compact-report" onClick={() => navigate("report")}><FileSpreadsheet size={17} /> 보고서</button>}
        </div>
        <div className="page-content" aria-busy={busy}>
          {task && <div className="notice work" role="status"><LoaderCircle className="spinner" size={18} /> {task}</div>}
          {error && <div className="notice error" role="alert">{error}{!connected && <button className="button secondary" disabled={busy} onClick={() => void load()}>다시 연결</button>}</div>}
          {notice && <div className="notice success" role="status"><Check size={18} />{notice}<button className="button icon dismiss" onClick={() => setNotice("")} aria-label="알림 닫기"><X size={16} /></button></div>}
          {booting && <div className="card"><Empty><span role="status">작업 공간을 불러오는 중…</span></Empty></div>}
          {!booting && connected && <>
            {stale && page !== "report" && <div className="notice warning">분석 조건이 변경되었습니다. 새 조건을 반영하려면 분석을 실행하세요.</div>}
            {page === "overview" && <>
              <SourcePanel source={source} busy={busy} onUpload={(file) => void upload(file)} onChange={(change) => void changeSource(change)}
                onRemove={removeSource} onRaw={() => navigate("raw")} />
              <Conditions source={source} options={options} busy={busy} pendingCount={pendingCount} onChange={(change) => setOptions({ ...options, ...change })} onRun={() => analyze(pendingCount > 0)} />
              {analysis && <>
                <Metrics analysis={analysis} />
                <ChartPanel mode="overview" analysis={analysis} revision={revision} onHistory={showHistory} />
                <section className="card notes-card">
                  <h2>분석 기준</h2>
                  <p>{display(analysis.metrics.period)}</p>
                  <details><summary>집계 기준 및 유의 사항 보기</summary><ul>{analysis.notes.map((note, index) => <li key={index}>{note}</li>)}</ul></details>
                </section>
              </>}
            </>}
            {resultPages.has(page) && !analysis && <section className="card">
              <Empty>분석 결과가 생기면 확인할 수 있습니다.<button className="button secondary" onClick={() => navigate("overview")}><FolderOpen size={17} /> 분석 개요</button></Empty>
            </section>}
            {page === "breakdown" && analysis && <BreakdownTables analysis={analysis} revision={revision} onHistory={showHistory} onOpen={openEvent} />}
            {page === "trend" && analysis && <ChartPanel mode="trend" analysis={analysis} revision={revision} onHistory={showHistory} />}
            {page === "compare" && analysis && <ComparisonPanel revision={revision} />}
            {analysis && (page === "review" || page === "history") && <section className="card">
              <div className="section-heading">
                <div><h2>{page === "review" ? "검토 필요" : "표준화 기록"}</h2>
                  <p>{page === "review" ? `${display(analysis.metrics.review_rows)}건 검토 필요 · ${display(pendingCount)}건 확정 대기` : "기록을 열어 분류 근거와 원본 행을 확인하세요."}</p>
                </div>
                {pendingCount > 0 && <button className="button primary" disabled={busy} onClick={() => analyze(true)}><Check size={17} /> 분류 적용 및 재분석</button>}
              </div>
              {filter && <div className="filter-chip">{filter.also && `${filter.also.value} · `}{filter.value}<button className="button icon" onClick={() => setFilter(undefined)} aria-label="집계 필터 제거"><X size={15} /></button></div>}
              <DataGrid key={`${page}/${JSON.stringify(filter)}`} revision={revision} tableKey={page === "review" ? "review" : "detail"}
                filter={filter} onOpen={openEvent} colors={settings?.review_colors} />
            </section>}
            {page === "raw" && <section className="card">
              <div className="section-heading"><div><h2>{source?.sheet ?? "원본 미리보기"}</h2></div></div>
              {source ? <DataGrid tableKey="raw" revision={revision} /> : <Empty>분석 개요에서 고장이력 파일을 올리세요.</Empty>}
            </section>}
            {page === "report" && <ReportPanel key={settingsRevision} settings={settings} canExport={!!source} busy={busy} pendingCount={pendingCount}
              stale={stale} onSave={saveSettings} onDownload={download} />}
            {page === "settings" && <SettingsPanel settings={settings} busy={busy} onSave={saveSettings} revision={settingsRevision} />}
          </>}
        </div>
      </main>
      {selected && <EventDrawer key={eventPath(selected)} row={selected} revision={revision} busy={busy} settings={settings}
        error={drawerError} onClose={() => setSelected(undefined)} onSave={saveEvent} />}
    </div>
  );
}
