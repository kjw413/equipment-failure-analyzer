"use client";

import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { api, display, params, type RecordRow, type Table } from "./lib";

export type Filter = { field: string; value: string; also?: { field: string; value: string } };
const historyColumns = new Set(["date", "line", "equipment", "major", "detail_equipment", "minor", "normalized", "status", "minutes", "repair_actions"]);
const reviewColumns = new Set(["source_row", "raw_description", "review_reason", "review_action", "status", "normalized", "detail_equipment", "type"]);

export function useApi<T>(path: string | null, revision = 0) {
  const [response, setResponse] = useState<{ path: string; revision: number; data?: T; error?: string }>();
  useEffect(() => {
    if (!path) return;
    const abort = new AbortController();
    api<T>(path, { signal: abort.signal })
      .then((data) => { if (!abort.signal.aborted) setResponse({ path, revision, data }); })
      .catch((error: unknown) => {
        if (!abort.signal.aborted) setResponse({ path, revision, error: (error as Error).message });
      });
    return () => abort.abort();
  }, [path, revision]);

  const current = response?.path === path && response.revision === revision ? response : undefined;
  return { data: current?.data, error: current?.error, loading: !!path && !current };
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function DataGrid({
  tableKey, revision, filter, query: suppliedQuery = "", onOpen, onDrill, drillLabel = "이력 보기", colors,
}: {
  tableKey: string;
  revision: number;
  filter?: Filter;
  query?: string;
  onOpen?: (row: RecordRow) => void;
  onDrill?: (row: RecordRow) => void;
  drillLabel?: string;
  colors?: Record<string, string>;
}) {
  const [query, setQuery] = useState(suppliedQuery);
  const [searched, setSearched] = useState(suppliedQuery);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [sort, setSort] = useState<{ key: string; order: "asc" | "desc" }>();
  const [extra, setExtra] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearched(query.trim());
      setOffset(0);
    }, 220);
    return () => window.clearTimeout(timer);
  }, [query]);
  const { data, error, loading } = useApi<Table>(`/table/${encodeURIComponent(tableKey)}${params({
    offset, limit: pageSize, q: searched, sort: sort?.key, order: sort?.order,
    filter_field: filter?.field, filter_value: filter?.value,
    filter_field2: filter?.also?.field, filter_value2: filter?.also?.value,
  })}`, revision);
  const total = data?.total ?? 0;
  const visibleColumns = tableKey === "detail" ? historyColumns : tableKey === "review" ? reviewColumns : undefined;
  const columns = data?.columns.filter(({ key }) => !visibleColumns || extra || visibleColumns.has(key)) ?? [];
  const actions = !!onOpen || !!onDrill;
  const lastPage = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = Math.floor(offset / pageSize) + 1;

  useEffect(() => {
    if (data && currentPage > lastPage) setOffset((lastPage - 1) * pageSize);
  }, [data, currentPage, lastPage, pageSize]);

  return (
    <div className="grid-shell">
      <div className="toolbar">
        <label className="search">
          <Search size={17} aria-hidden />
          <input value={query} maxLength={300} onChange={(event) => setQuery(event.target.value)} placeholder="기록 검색" aria-label="기록 검색" />
        </label>
        {visibleColumns && <label className="checkbox"><input type="checkbox" checked={extra} onChange={(event) => {
          setExtra(event.target.checked);
          if (!event.target.checked && sort && !visibleColumns.has(sort.key)) setSort(undefined);
        }} /> 추가 열 표시</label>}
        <label className="single-line">
          페이지당
          <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setOffset(0); }}>
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </label>
      </div>
      {loading && <Empty><span role="status">기록을 불러오는 중…</span></Empty>}
      {error && <div className="notice error" role="alert">{error}</div>}
      {data && <div className="table-scroll" tabIndex={0} aria-label="분석 기록">
        <table>
          <thead>
            <tr>
              {columns.map(({ key, label }) => {
                const current = sort?.key === key ? sort.order : undefined;
                const SortIcon = current === "asc" ? ArrowUp : current === "desc" ? ArrowDown : ArrowUpDown;
                return <th key={key} scope="col" aria-sort={current === "asc" ? "ascending" : current === "desc" ? "descending" : "none"}>
                  <button className="sort-button" onClick={() => { setSort({ key, order: current === "asc" ? "desc" : "asc" }); setOffset(0); }}>
                    {label} <SortIcon size={13} aria-hidden />
                  </button>
                </th>;
              })}
              {actions && <th scope="col" className="row-actions">작업</th>}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, index) => <tr key={`${row.event_id ?? ""}/${row.source_row ?? offset + index}`}>
              {columns.map(({ key }) => <td className={typeof row[key] === "number" ? "numeric" : undefined} key={key}>
                {display(key === "date" && typeof row[key] === "string" ? row[key].slice(0, 10) : row[key])}
              </td>)}
              {actions && <td className="row-actions">
                {!!row.pending_classification && <span className="row-state">확정 대기</span>}
                {!!row.review_color_key && colors?.[String(row.review_color_key)] &&
                  <span className="review-tone" style={{ backgroundColor: colors[String(row.review_color_key)] }} aria-label="검토 표시" />}
                {onOpen && row.event_id != null && <button className="link-button" onClick={() => onOpen(row)}>상세 보기</button>}
                {onDrill && <button className="link-button" onClick={() => onDrill(row)}>{drillLabel}</button>}
              </td>}
            </tr>)}
            {!data.rows.length && <tr><td colSpan={columns.length + Number(actions) || 1} className="table-empty">조건에 맞는 기록이 없습니다.</td></tr>}
          </tbody>
        </table>
      </div>}
      <div className="grid-footer">
        <span>{total ? `${display(offset + 1)}–${display(Math.min(offset + pageSize, total))} / ${display(total)}건` : "0건"}</span>
        <div className="pagination">
          <button className="button icon" onClick={() => setOffset(Math.max(0, offset - pageSize))} disabled={!offset || loading} aria-label="이전 페이지"><ChevronLeft size={18} /></button>
          <span>{currentPage} / {lastPage}</span>
          <button className="button icon" onClick={() => setOffset(offset + pageSize)} disabled={currentPage >= lastPage || loading} aria-label="다음 페이지"><ChevronRight size={18} /></button>
        </div>
      </div>
    </div>
  );
}
