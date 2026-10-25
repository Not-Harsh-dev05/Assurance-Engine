"""HTTP application for the deletion assurance dashboard."""

import csv
import json
import logging
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from assurance_engine.deletion_requests import (
    DeletionRequest,
    DeletionRequestCSVError,
    load_deletion_requests,
    load_deletion_requests_text,
)
from assurance_engine.engine import verify
from assurance_engine.schemas import VerificationPolicy, Verdict

logger = logging.getLogger("assurance_engine.webapp")

WEB_DIR = Path(__file__).parent / "web"
MAX_IMPORT_BYTES = 5 * 1024 * 1024
RESULT_COLUMNS = ("case_id", "deletion_status", "steps_json")
AUDIT_INPUTS = (
    ("user_identities.csv", "CSV"),
    ("user_audit_log.csv", "CSV"),
    ("system_activity.csv", "CSV"),
    ("deletion_rules.csv", "CSV"),
    ("evidence_files.csv", "CSV"),
    ("evidence", "directory"),
)


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class AuditApplicationState:
    def __init__(self, dataset_dir: Path) -> None:
        self.dataset_dir = dataset_dir
        self.lock = RLock()
        self.requests: list[DeletionRequest] = []
        self.request_source = dataset_dir / "deletion_requests.csv"
        self.request_uploaded_name: str | None = None
        self.load_error: str | None = None
        self.results: dict[str, dict[str, Any]] = {}
        self.last_run_at: str | None = None
        if self.request_source.is_file():
            self._load_initial_requests()

    def _load_initial_requests(self) -> None:
        try:
            self.requests = load_deletion_requests(self.request_source)
        except DeletionRequestCSVError as error:
            self.load_error = str(error)
            logger.exception("Unable to load deletion requests")

    def inventory(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        request_path = self.request_source
        if self.request_uploaded_name:
            items.append(
                {
                    "name": "deletion_requests.csv",
                    "path": "In-memory upload; original dataset was not changed",
                    "kind": "CSV",
                    "available": True,
                    "has_data": bool(self.requests),
                    "record_count": len(self.requests),
                    "columns": [
                        "case_id",
                        "email",
                        "requested_at",
                        "reported_status",
                        "reported_at",
                        "audit_at",
                        "request_text",
                    ],
                    "loaded_from": self.request_uploaded_name,
                }
            )
        else:
            items.append(self._file_inventory("deletion_requests.csv", request_path))

        for filename, kind in AUDIT_INPUTS:
            path = self.dataset_dir / filename
            if kind == "directory":
                exists = path.is_dir()
                files = (
                    [
                        {
                            "name": child.relative_to(path).as_posix(),
                            "bytes": child.stat().st_size,
                        }
                        for child in sorted(path.rglob("*"))
                        if child.is_file()
                    ]
                    if exists
                    else []
                )
                items.append(
                    {
                        "name": filename,
                        "path": str(path),
                        "kind": kind,
                        "available": exists,
                        "has_data": any(item["bytes"] > 0 for item in files),
                        "record_count": len(files),
                        "files": files,
                    }
                )
            else:
                items.append(self._file_inventory(filename, path))
        return items

    @staticmethod
    def _file_inventory(name: str, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {
                "name": name,
                "path": str(path),
                "kind": "CSV",
                "available": False,
                "has_data": False,
                "record_count": 0,
            }
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream)
                header = next(reader, None)
                row_count = sum(1 for row in reader if row)
            return {
                "name": name,
                "path": str(path),
                "kind": "CSV",
                "available": True,
                "has_data": row_count > 0,
                "record_count": row_count,
                "columns": header or [],
                "bytes": path.stat().st_size,
            }
        except (OSError, UnicodeError, csv.Error) as error:
            logger.exception("Unable to inspect dataset input %s", path)
            return {
                "name": name,
                "path": str(path),
                "kind": "CSV",
                "available": True,
                "has_data": False,
                "record_count": 0,
                "error": str(error),
            }

    def missing_audit_inputs(self) -> list[str]:
        return [
            item["name"]
            for item in self.inventory()[1:]
            if not item["available"] or not item["has_data"]
        ]

    def run_audit(self) -> dict[str, Any]:
        with self.lock:
            if not self.requests:
                raise ApiError(
                    409,
                    "NO_REQUESTS",
                    "Load a valid deletion-request CSV before running verification.",
                )

            inventory = self.inventory()
            missing_inputs = [
                item["name"]
                for item in inventory[1:]
                if not item["available"] or not item["has_data"]
            ]
            evidence_gaps = [
                {
                    "code": "AUDIT_INPUT_MISSING",
                    "source": name,
                    "message": (
                        f"Required source {name!r} is missing or contains no data."
                    ),
                }
                for name in missing_inputs
            ]
            if not missing_inputs:
                evidence_gaps.append(
                    {
                        "code": "EVIDENCE_SCHEMA_UNMAPPED",
                        "source": "dataset",
                        "message": (
                            "Source files are present, but their records have "
                            "not been mapped to deterministic deletion-policy checks."
                        ),
                    }
                )

            policy = VerificationPolicy(
                policy_id="deletion-audit-evidence",
                claim_field="deletion_status",
                expected_value="COMPLETE",
                require_trusted_evidence=True,
            )
            results: dict[str, dict[str, Any]] = {}
            for request_item in self.requests:
                verification = verify(
                    f"Deletion request {request_item.case_id} is verified complete",
                    [],
                    policy,
                )
                if verification.verdict == Verdict.VERIFIED:
                    deletion_status = "COMPLETE"
                else:
                    deletion_status = "INCOMPLETE"

                steps = self._remediation_steps(missing_inputs)
                findings = [
                    {
                        "code": "REPORTED_STATUS_UNVERIFIED",
                        "message": (
                            f"The request file reports "
                            f"{request_item.reported_status}; this claim does "
                            "not establish deletion."
                        ),
                    },
                    {
                        "code": "INSUFFICIENT_TRUSTED_EVIDENCE",
                        "message": (
                            "The deterministic verification engine received no "
                            "trusted deletion evidence, so completion cannot be "
                            "verified."
                        ),
                    },
                ]
                results[request_item.case_id] = {
                    "case_id": request_item.case_id,
                    "deletion_status": deletion_status,
                    "steps": steps,
                    "findings": findings,
                    "supporting_evidence": [],
                    "evidence_gaps": evidence_gaps,
                    "reported_status": request_item.reported_status,
                    "engine_verdict": verification.verdict.value,
                }

            run_at = datetime.now(timezone.utc).isoformat()
            self._write_output(results)
            self.results = results
            self.last_run_at = run_at
            logger.info(
                "Audit run completed: requests=%d, status_counts=%s, missing_inputs=%s",
                len(results),
                dict(Counter(row["deletion_status"] for row in results.values())),
                missing_inputs,
            )
            return self.dashboard()

    @staticmethod
    def _remediation_steps(missing_inputs: list[str]) -> list[str]:
        steps: list[str] = []
        if "user_identities.csv" in missing_inputs:
            steps.append(
                "Provide user_identities.csv and correlate current and historical identifiers to the request."
            )
        if "user_audit_log.csv" in missing_inputs:
            steps.append(
                "Provide user_audit_log.csv and verify the recorded deletion actions and retained records."
            )
        if "system_activity.csv" in missing_inputs:
            steps.append(
                "Provide system_activity.csv and check for active sync, import, or restore processes."
            )
        if "deletion_rules.csv" in missing_inputs:
            steps.append(
                "Provide deletion_rules.csv and determine which records require deletion, retention, or tombstoning."
            )
        if "evidence_files.csv" in missing_inputs or "evidence" in missing_inputs:
            steps.append(
                "Provide the evidence index and evidence files, then inspect each referenced artifact."
            )
        if not steps:
            steps.extend(
                [
                    "Map the supplied identity, audit, activity, rules, and evidence records to deterministic policy checks.",
                    "Verify identifier history, deletion actions, retention exceptions, permitted tombstones, and recreation paths.",
                ]
            )
        steps.append(
            "Rerun verification after the evidence gaps are resolved; do not treat the reported status as proof."
        )
        return steps

    def _write_output(self, results: dict[str, dict[str, Any]]) -> None:
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.dataset_dir / "output.csv"
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=self.dataset_dir,
                prefix=".output-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temp_path = Path(stream.name)
                writer = csv.DictWriter(stream, fieldnames=RESULT_COLUMNS)
                writer.writeheader()
                for case_id, result in results.items():
                    writer.writerow(
                        {
                            "case_id": case_id,
                            "deletion_status": result["deletion_status"],
                            "steps_json": json.dumps(
                                result["steps"],
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        }
                    )
            os.replace(temp_path, output_path)
        except OSError as error:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            logger.exception("Unable to write audit result CSV")
            raise ApiError(
                500,
                "OUTPUT_WRITE_FAILED",
                f"Could not write audit results to {output_path}.",
                str(error),
            ) from error

    def dashboard(self) -> dict[str, Any]:
        counts = Counter(
            result["deletion_status"] for result in self.results.values()
        )
        missing_inputs = self.missing_audit_inputs()
        return {
            "request_count": len(self.requests),
            "status_counts": {
                status: counts.get(status, 0)
                for status in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")
            },
            "audit_inputs_ready": bool(self.requests) and not missing_inputs,
            "decision_checks_available": False,
            "audit_ready": False,
            "has_results": bool(self.results),
            "last_run_at": self.last_run_at,
            "missing_inputs": missing_inputs,
            "load_error": self.load_error,
        }


def _request_as_dict(request_item: DeletionRequest) -> dict[str, Any]:
    return {
        "case_id": request_item.case_id,
        "email": request_item.email,
        "requested_at": request_item.requested_at.isoformat(),
        "reported_status": request_item.reported_status,
        "reported_at": request_item.reported_at.isoformat(),
        "audit_at": request_item.audit_at.isoformat(),
        "request_text": request_item.request_text,
    }


def create_app(dataset_dir: Path | None = None) -> FastAPI:
    resolved_dataset = (
        dataset_dir
        if dataset_dir is not None
        else Path(os.environ.get("ASSURANCE_DATASET_DIR", "dataset"))
    ).resolve()
    state = AuditApplicationState(resolved_dataset)
    app = FastAPI(
        title="Ghost Data Still Exists",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.audit = state
    app.mount(
        "/assets",
        StaticFiles(directory=WEB_DIR),
        name="assets",
    )

    @app.exception_handler(ApiError)
    async def api_error_handler(
        _request: Request, error: ApiError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": error.details,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "The request contains invalid parameters.",
                    "details": error.errors(),
                }
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        _request: Request, error: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled application error", exc_info=error)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "The request could not be completed.",
                    "details": None,
                }
            },
        )

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "ghost-data-assurance"}

    @app.get("/api/dashboard")
    async def dashboard() -> dict[str, Any]:
        return state.dashboard()

    @app.get("/api/datasets")
    async def datasets() -> dict[str, Any]:
        return {
            "dataset_dir": str(state.dataset_dir),
            "inputs": state.inventory(),
            "request_load_error": state.load_error,
        }

    @app.post("/api/import/requests")
    async def import_requests(request: Request) -> dict[str, Any]:
        filename = request.headers.get("x-filename", "upload.csv")
        if Path(filename).name != filename or not filename.lower().endswith(".csv"):
            raise ApiError(
                400,
                "INVALID_FILENAME",
                "Upload a .csv filename without directory components.",
            )
        content_type = request.headers.get("content-type", "").split(";")[0]
        if content_type not in {
            "text/csv",
            "application/csv",
            "text/plain",
            "application/octet-stream",
        }:
            raise ApiError(
                415,
                "UNSUPPORTED_MEDIA_TYPE",
                "Upload the CSV file as text/csv.",
            )
        content = await request.body()
        if not content:
            raise ApiError(400, "EMPTY_UPLOAD", "The uploaded CSV is empty.")
        if len(content) > MAX_IMPORT_BYTES:
            raise ApiError(
                413,
                "UPLOAD_TOO_LARGE",
                f"CSV uploads are limited to {MAX_IMPORT_BYTES} bytes.",
            )
        try:
            text = content.decode("utf-8-sig")
            imported = load_deletion_requests_text(
                text,
                source_name=filename,
            )
        except UnicodeDecodeError as error:
            raise ApiError(
                400,
                "INVALID_ENCODING",
                "The uploaded CSV must be UTF-8 encoded.",
            ) from error
        except DeletionRequestCSVError as error:
            raise ApiError(
                422,
                "INVALID_REQUEST_CSV",
                str(error),
            ) from error

        with state.lock:
            state.requests = imported
            state.request_uploaded_name = filename
            state.load_error = None
            state.results = {}
            state.last_run_at = None
        logger.info("Imported %d deletion requests from %s", len(imported), filename)
        return {
            "filename": filename,
            "request_count": len(imported),
            "validated": True,
            "audit_required": True,
            "message": "CSV validated and loaded in memory; the dataset file was not overwritten.",
        }

    @app.get("/api/cases")
    async def list_cases(
        search: str = Query(default="", max_length=200),
        status: str = Query(default="", max_length=32),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
    ) -> dict[str, Any]:
        allowed_statuses = {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}
        if status and status not in allowed_statuses:
            raise ApiError(
                422,
                "INVALID_STATUS_FILTER",
                f"Status must be one of {', '.join(sorted(allowed_statuses))}.",
            )
        normalized_search = search.casefold().strip()
        with state.lock:
            filtered = [
                item
                for item in state.requests
                if (
                    not normalized_search
                    or normalized_search
                    in " ".join(
                        (
                            item.case_id,
                            item.email,
                            item.reported_status,
                            item.request_text,
                        )
                    ).casefold()
                )
                and (
                    not status
                    or state.results.get(item.case_id, {}).get(
                        "deletion_status"
                    )
                    == status
                )
            ]
            total = len(filtered)
            start = (page - 1) * page_size
            items = []
            for request_item in filtered[start : start + page_size]:
                result = state.results.get(request_item.case_id)
                items.append(
                    {
                        **_request_as_dict(request_item),
                        "result": result,
                    }
                )
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size,
        }

    @app.get("/api/cases/{case_id}")
    async def get_case(case_id: str) -> dict[str, Any]:
        with state.lock:
            request_item = next(
                (item for item in state.requests if item.case_id == case_id),
                None,
            )
            if request_item is None:
                raise ApiError(404, "CASE_NOT_FOUND", f"Case {case_id!r} was not found.")
            return {
                "case": _request_as_dict(request_item),
                "result": state.results.get(case_id),
            }

    @app.post("/api/audits/run")
    async def run_audit() -> dict[str, Any]:
        return state.run_audit()

    @app.get("/api/results")
    async def get_results(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
        status: str = Query(default="", max_length=32),
    ) -> dict[str, Any]:
        if not state.results:
            raise ApiError(
                409,
                "AUDIT_NOT_RUN",
                "Run verification before requesting results.",
            )
        if status and status not in {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}:
            raise ApiError(422, "INVALID_STATUS_FILTER", "Unknown result status.")
        items = list(state.results.values())
        if status:
            items = [item for item in items if item["deletion_status"] == status]
        total = len(items)
        start = (page - 1) * page_size
        return {
            "items": items[start : start + page_size],
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size,
            "last_run_at": state.last_run_at,
        }

    @app.get("/api/results/export.csv")
    async def export_results() -> Response:
        if not state.results:
            raise ApiError(
                409,
                "AUDIT_NOT_RUN",
                "Run verification before exporting results.",
            )
        from io import StringIO

        output = StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        for case_id, result in state.results.items():
            writer.writerow(
                {
                    "case_id": case_id,
                    "deletion_status": result["deletion_status"],
                    "steps_json": json.dumps(
                        result["steps"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="output.csv"'
            },
        )

    return app


app = create_app()


def run() -> None:
    import uvicorn

    logging.basicConfig(
        level=os.environ.get("ASSURANCE_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(
        app,
        host=os.environ.get("ASSURANCE_HOST", "127.0.0.1"),
        port=int(os.environ.get("ASSURANCE_PORT", "8000")),
        log_config=None,
    )
