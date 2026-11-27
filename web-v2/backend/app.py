"""HTTP API for the local web workspace."""

from __future__ import annotations

import os
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import pandas as pd
from fastapi import Depends, FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask
from workspace import Workspace, records, table_payload

from core.issue_analysis import issue_summary, select_issues
from core.models import AnalysisOptions, UserError
from report.export_bundle import export_bundle
from report.fault_comparison import comparison_facts, line_catalog


@asynccontextmanager
async def lifespan(app: FastAPI):
    default_path = Path(__file__).resolve().parents[1] / ".data"
    workspace = Workspace(
        Path(os.environ.get("EFA_WEB_DATA_DIR") or default_path).expanduser().resolve()
    )
    app.state.workspace = workspace
    try:
        if source := os.environ.get("EFA_WEB_INITIAL_SOURCE"):
            workspace.load_source(Path(source))
        yield
    finally:
        workspace.reset()


app = FastAPI(title="설비 고장 분석기 v2", version="2.0.0", lifespan=lifespan)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@app.middleware("http")
async def restrict_to_local_browser(request: Request, call_next):
    try:
        local_host = urlsplit("//" + request.headers.get("host", "")).hostname in LOCAL_HOSTS
    except ValueError:
        local_host = False
    if not local_host:
        return JSONResponse(status_code=403, content={"detail": "로컬 주소로 접속해주세요."})
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        try:
            local_origin = origin is None or urlsplit(origin).hostname in LOCAL_HOSTS
        except ValueError:
            local_origin = False
        if not local_origin or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse(
                status_code=403, content={"detail": "다른 사이트에서는 작업을 변경할 수 없습니다."}
            )
    return await call_next(request)


@app.exception_handler(UserError)
async def user_error(_request: Request, exc: UserError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, exc: RequestValidationError) -> JSONResponse:
    error = exc.errors()[0]
    field = ".".join(str(part) for part in error["loc"][1:])
    return JSONResponse(
        status_code=422,
        content={"detail": f"입력값을 확인하세요. ({field}: {error['msg']})"},
    )


def get_workspace(request: Request) -> Workspace:
    return request.app.state.workspace


WorkspaceDep = Annotated[Workspace, Depends(get_workspace)]


class SourceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sheet: str | None = None
    header_row: int | None = Field(default=None, ge=1, le=250_000)
    mapping: dict[str, str | None] | None = None


class AnalysisSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["fault", "all"] = "fault"
    equipment_basis: Literal[
        "mapped", "group", "factory", "team", "target", "registered", "family"
    ] = "mapped"
    date_from: date | None = None
    date_to: date | None = None
    duration_unit: Literal["minutes", "hours", "seconds", "excel_days"] = "minutes"
    deduplicate: bool = False
    top_n: int = Field(default=10, ge=1, le=30)
    factory: str | None = None
    team: str | None = None

    def to_options(self) -> AnalysisOptions:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise UserError("시작일은 종료일보다 늦을 수 없습니다.")
        return AnalysisOptions(**self.model_dump(mode="json"))


class Correction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, str | None]
    confirm: bool = False


class EquipmentNames(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["line", "equipment"]
    mapping: dict[str, str]
    grouping: dict | None = None
    organization: dict | None = None


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": app.version}


@app.get("/api/source")
def get_source(workspace: WorkspaceDep) -> dict | None:
    with workspace.lock:
        return workspace.source_summary()


@app.post("/api/source")
def upload_source(workspace: WorkspaceDep, file: Annotated[UploadFile, File()]) -> dict:
    with workspace.lock:
        return workspace.upload_source(file.filename or "", file.file)


@app.patch("/api/source")
def change_source(workspace: WorkspaceDep, settings: SourceSettings) -> dict:
    with workspace.lock:
        return workspace.change_source(
            settings.sheet,
            settings.header_row,
            settings.mapping,
            auto_header=(
                "header_row" in settings.model_fields_set
                or bool(settings.sheet and settings.sheet != workspace.require_source().sheet)
            ),
        )


@app.delete("/api/source", status_code=204)
def delete_source(workspace: WorkspaceDep) -> None:
    with workspace.lock:
        workspace.reset()


@app.get("/api/analysis")
def get_analysis(workspace: WorkspaceDep) -> dict | None:
    with workspace.lock:
        return workspace.analysis_summary()


@app.post("/api/analysis")
def analyze(workspace: WorkspaceDep, settings: AnalysisSettings) -> dict:
    with workspace.lock:
        return workspace.analyze(settings.to_options())


@app.post("/api/standardize")
def standardize(workspace: WorkspaceDep, settings: AnalysisSettings) -> dict:
    with workspace.lock:
        return workspace.analyze(settings.to_options(), apply_pending=True)


def sort_column(values: pd.Series) -> pd.Series:
    if pd.api.types.is_object_dtype(values.dtype) or pd.api.types.is_string_dtype(values.dtype):
        return values.astype("string").str.casefold()
    return values


def filter_rows(frame: pd.DataFrame, field: str | None, value: str | None) -> pd.DataFrame:
    if not field or value is None:
        return frame
    if field == "period" and "period" not in frame and "date" in frame:
        dates = pd.to_datetime(frame["date"], errors="coerce")
        return frame.loc[dates.dt.strftime("%Y-%m-%d").str.startswith(value, na=False)]
    if field not in frame:
        raise UserError("현재 표에 없는 필터입니다.")
    values = frame[field]
    if pd.api.types.is_datetime64_any_dtype(values.dtype):
        values = values.dt.strftime("%Y-%m-%d")
    return frame.loc[values.astype("string").eq(value).fillna(False)]


@app.get("/api/table/{key}")
def table(
    workspace: WorkspaceDep,
    key: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    q: Annotated[str, Query(max_length=300)] = "",
    sort: str | None = None,
    order: Literal["asc", "desc"] = "asc",
    filter_field: str | None = None,
    filter_value: str | None = None,
    filter_field2: str | None = None,
    filter_value2: str | None = None,
) -> dict:
    with workspace.lock:
        frame = workspace.table_frame(key)
        frame = filter_rows(frame, filter_field, filter_value)
        frame = filter_rows(frame, filter_field2, filter_value2)
        if q.strip() and not frame.empty:
            matches = pd.Series(False, index=frame.index)
            for _, values in frame.items():
                matches |= values.astype("string").str.contains(
                    q.strip(), case=False, regex=False, na=False
                )
            frame = frame.loc[matches]
        if sort:
            if sort not in frame:
                raise UserError("현재 표에 없는 정렬 열입니다.")
            frame = frame.sort_values(
                sort, ascending=order == "asc", kind="stable", key=sort_column, na_position="last"
            )
        payload = table_payload(frame.iloc[offset : offset + limit], len(frame), raw=key == "raw")
        if key in ("detail", "review", "long_stops"):
            workspace.add_review_metadata(payload["rows"])
        return payload


@app.get("/api/events/{event_id}")
def get_event(workspace: WorkspaceDep, event_id: str, source_row: int | None = None) -> dict:
    with workspace.lock:
        return workspace.event(event_id, source_row)


@app.patch("/api/events/{event_id}")
def edit_event(
    workspace: WorkspaceDep, event_id: str, edit: Correction, source_row: int | None = None
) -> dict:
    with workspace.lock:
        return workspace.edit_event(event_id, source_row, edit.values, edit.confirm)


COMPARISON_AXES = ("factory", "team", "line", "family", "module", "symptom")


def comparison_summary(selected: pd.DataFrame) -> dict:
    total = selected["minutes"].sum(min_count=1)
    fields = ["factory", "team", "line", "module", "symptom"]
    groups = issue_summary(selected, fields)
    return {
        "count": len(selected),
        "total_minutes": None if pd.isna(total) else float(total),
        "rows": records(groups.head(100)),
        "group_count": len(groups),
    }


@app.get("/api/comparison")
def comparison(workspace: WorkspaceDep, request: Request) -> dict:
    with workspace.lock:
        facts = comparison_facts(workspace.require_result())
        catalog = line_catalog(facts)
        choices = dict(zip(zip(catalog.factory, catalog.team, catalog.asset), catalog.choice))
        facts["line"] = [
            choices[identity] for identity in zip(facts.factory, facts.team, facts.asset)
        ]
        baseline, candidate = [
            select_issues(
                facts,
                **{
                    axis: request.query_params.get(prefix + axis) or None
                    for axis in COMPARISON_AXES
                },
            )
            for prefix in ("base_", "compare_")
        ]
        eligible = candidate.loc[~candidate["record_id"].isin(baseline["record_id"])]
        return {
            "choices": {
                axis: sorted(facts[axis].dropna().unique().tolist()) for axis in COMPARISON_AXES
            },
            "base": comparison_summary(baseline),
            "comparison": comparison_summary(eligible),
        }


EXCEL_MEDIA_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
}


@app.get("/api/export")
def export(workspace: WorkspaceDep, format: Literal["xlsx", "xlsm"] = "xlsm") -> FileResponse:
    with workspace.lock:
        result = workspace.require_result()
        directory = tempfile.TemporaryDirectory(prefix="efa-report-", dir=workspace.store.root)
        filename = f"Equipment_Analysis_{datetime.now():%Y%m%d_%H%M%S}.{format}"
        try:
            path = export_bundle(result, Path(directory.name) / filename).excel
        except BaseException:
            directory.cleanup()
            raise
        return FileResponse(
            path,
            filename=filename,
            media_type=EXCEL_MEDIA_TYPES[format],
            background=BackgroundTask(directory.cleanup),
        )


@app.get("/api/settings")
def get_settings(workspace: WorkspaceDep) -> dict:
    with workspace.lock:
        return workspace.settings()


@app.patch("/api/settings/report")
def save_report_settings(workspace: WorkspaceDep, fields: dict[str, str | bool]) -> dict:
    with workspace.lock:
        workspace.store.save_report_settings(fields)
        workspace.refresh_result()
        return workspace.settings()


@app.patch("/api/settings/review-colors")
def save_colors(workspace: WorkspaceDep, colors: dict[str, str]) -> dict:
    with workspace.lock:
        workspace.store.save_review_colors(colors)
        workspace.refresh_result()
        return workspace.settings()


@app.patch("/api/settings/equipment-names")
def save_names(workspace: WorkspaceDep, names: EquipmentNames) -> dict:
    with workspace.lock:
        workspace.save_names(names.mapping, names.source, names.grouping, names.organization)
        return workspace.settings()


@app.put("/api/settings/rules")
def save_rules(workspace: WorkspaceDep, rules: list[dict]) -> dict:
    with workspace.lock:
        workspace.save_rules(rules)
        return workspace.settings()
