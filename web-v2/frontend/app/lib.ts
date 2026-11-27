export type Scalar = string | number | boolean | null;
export type RecordRow = Record<string, unknown>;
export type Mapping = Record<string, string | null>;
export type Source = {
  name: string;
  sheet: string;
  header_row: number;
  sheet_names: string[];
  headers: string[];
  mapping: Mapping;
  fields: Record<string, string>;
  row_count: number;
  skipped_count: number;
  warnings: string[];
  profile: string;
  factories: string[];
  teams: string[];
  organizations: Record<string, string[]>;
};
export type AnalysisOptions = {
  scope: string;
  equipment_basis: string;
  date_from: string | null;
  date_to: string | null;
  duration_unit: string;
  deduplicate: boolean;
  top_n: number;
  factory: string | null;
  team: string | null;
};
export type TableRef = { key: string; label: string; count: number };
export type Analysis = {
  metrics: RecordRow;
  notes: string[];
  tables: TableRef[];
  options: AnalysisOptions;
  pending_count: number;
};
export type Column = { key: string; label: string };
export type Table = { columns: Column[]; rows: RecordRow[]; total: number };
export type EventDetail = {
  record: RecordRow;
  original: RecordRow | null;
  values: Record<string, Scalar>;
  pending: Record<string, Scalar> | null;
  overrides: Record<string, Scalar> | null;
  candidates?: RecordRow[];
};
export const comparisonFields = {
  factory: "공장",
  team: "팀",
  line: "라인",
  family: "설비",
  module: "상세설비",
  symptom: "고장유형",
};
export type ComparisonField = keyof typeof comparisonFields;
export type ComparisonGroup = { count: number; total_minutes: number | null; group_count: number; rows: RecordRow[] };
export type Comparison = {
  choices: Record<ComparisonField, string[]>;
  base: ComparisonGroup;
  comparison: ComparisonGroup;
};
export type Settings = {
  report: Record<string, Scalar>;
  review_colors: Record<string, string>;
  review_color_types: { key: string; label: string; default: string }[];
  equipment_names: {
    source: "line" | "equipment";
    mappings: Record<string, string>;
    line_mappings: Record<string, string>;
    grouping?: { mode: string; separator: string; overrides: Record<string, string> };
    organization?: Record<"line" | "equipment", Record<string, { factory?: string; team?: string }>>;
  };
  equipment_catalog: Record<"line" | "equipment", { code: string; raw_name: string }[]>;
  organization_catalog: Record<"line" | "equipment", Record<string, { factory?: string; team?: string }>>;
  rules: Record<string, Scalar>[];
  rule_columns: string[];
  classification_paths: string[][];
  repair_actions: string[];
};

export const defaultOptions: AnalysisOptions = {
  scope: "fault",
  equipment_basis: "mapped",
  date_from: null,
  date_to: null,
  duration_unit: "minutes",
  deduplicate: false,
  top_n: 10,
  factory: null,
  team: null,
};

export const display = (value: unknown): string => {
  if (value == null || value === "") return "—";
  if (typeof value === "number") return value.toLocaleString("ko-KR", { maximumFractionDigits: 3 });
  if (typeof value === "boolean") return value ? "예" : "아니요";
  if (Array.isArray(value)) return value.map(display).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
};

export function params(values: Record<string, Scalar | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value != null && value !== "") query.set(key, String(value));
  }
  const result = query.toString();
  return result ? `?${result}` : "";
}

export async function apiResponse(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (typeof init.body === "string") headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, headers, cache: "no-store" });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new Error("분석 서버에 연결할 수 없습니다. 서버 실행 상태를 확인하세요.");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    if (typeof body?.detail === "string") throw new Error(body.detail);
    if (Array.isArray(body?.detail)) {
      throw new Error(body.detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join(" · "));
    }
    if (response.status >= 500) throw new Error("분석 서버에서 요청을 처리하지 못했습니다.");
    throw new Error(`요청을 처리하지 못했습니다. (${response.status})`);
  }
  return response;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiResponse(path, init);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const json = (method: string, body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
});

export function eventPath(row: RecordRow) {
  return `/events/${encodeURIComponent(String(row.event_id))}${params({
    source_row: typeof row.source_row === "number" ? row.source_row : undefined,
  })}`;
}
