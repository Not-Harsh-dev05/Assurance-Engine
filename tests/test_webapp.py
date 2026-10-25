import csv
import io
import json

from fastapi.testclient import TestClient

from assurance_engine.webapp import RESULT_COLUMNS, create_app


REQUEST_HEADER = (
    "case_id,email,requested_at,reported_status,reported_at,audit_at,request_text"
)


def request_csv(*rows):
    return "\n".join((REQUEST_HEADER, *rows))


def valid_row(
    *,
    case_id="case_1",
    email="user@example.com",
    reported_status="COMPLETE",
):
    return (
        f"{case_id},{email},2026-01-01T10:00:00Z,"
        f"{reported_status},2026-01-02T10:00:00Z,"
        "2026-01-03T10:00:00Z,Please delete my account."
    )


def make_client(tmp_path, *, with_requests=True):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    if with_requests:
        (dataset / "deletion_requests.csv").write_text(
            request_csv(valid_row()),
            encoding="utf-8",
        )
    return TestClient(create_app(dataset))


def test_health_and_dashboard_endpoints(tmp_path):
    client = make_client(tmp_path)

    health = client.get("/api/health")
    dashboard = client.get("/api/dashboard")

    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "service": "ghost-data-assurance",
    }
    assert dashboard.json()["request_count"] == 1
    assert dashboard.json()["has_results"] is False
    assert dashboard.json()["status_counts"] == {
        "COMPLETE": 0,
        "INCOMPLETE": 0,
        "NOT_APPLICABLE": 0,
    }
    assert "user_identities.csv" in dashboard.json()["missing_inputs"]


def test_root_and_static_assets_are_served(tmp_path):
    client = make_client(tmp_path)

    assert client.get("/").status_code == 200
    assert "Deletion assurance" in client.get("/").text
    assert client.get("/assets/styles.css").status_code == 200
    assert client.get("/assets/app.js").status_code == 200


def test_dataset_inventory_reports_missing_inputs(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/datasets")

    assert response.status_code == 200
    entries = {item["name"]: item for item in response.json()["inputs"]}
    assert entries["deletion_requests.csv"]["available"] is True
    assert entries["deletion_requests.csv"]["record_count"] == 1
    assert entries["user_identities.csv"]["available"] is False
    assert entries["evidence"]["available"] is False


def test_import_validates_request_csv_in_memory(tmp_path):
    client = make_client(tmp_path)
    original = (tmp_path / "dataset" / "deletion_requests.csv").read_text(
        encoding="utf-8"
    )

    response = client.post(
        "/api/import/requests",
        content=request_csv(
            valid_row(case_id="case_2"),
            valid_row(
                case_id="case_3",
                email="second@example.com",
                reported_status="NOT_STARTED",
            ),
        ),
        headers={
            "content-type": "text/csv",
            "x-filename": "incoming.csv",
        },
    )

    assert response.status_code == 200
    assert response.json()["request_count"] == 2
    assert response.json()["validated"] is True
    assert "not overwritten" in response.json()["message"]
    assert (
        tmp_path / "dataset" / "deletion_requests.csv"
    ).read_text(encoding="utf-8") == original
    assert client.get("/api/cases").json()["total"] == 2


def test_import_rejects_invalid_schema_and_filename(tmp_path):
    client = make_client(tmp_path)

    wrong_columns = client.post(
        "/api/import/requests",
        content="email,case_id\nuser@example.com,case_2",
        headers={"content-type": "text/csv", "x-filename": "bad.csv"},
    )
    bad_filename = client.post(
        "/api/import/requests",
        content=request_csv(valid_row()),
        headers={"content-type": "text/csv", "x-filename": "..\\other.csv"},
    )

    assert wrong_columns.status_code == 422
    assert wrong_columns.json()["error"]["code"] == "INVALID_REQUEST_CSV"
    assert bad_filename.status_code == 400
    assert bad_filename.json()["error"]["code"] == "INVALID_FILENAME"


def test_invalid_api_query_returns_structured_validation_error(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/cases?page=0")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["message"]


def test_case_search_filter_pagination_and_details(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/import/requests",
        content=request_csv(
            valid_row(case_id="case_1"),
            valid_row(case_id="case_2", email="second@example.com"),
            valid_row(case_id="case_3", email="third@example.com"),
        ),
        headers={"content-type": "text/csv", "x-filename": "requests.csv"},
    )
    client.post("/api/audits/run")

    filtered = client.get("/api/cases?search=SECOND&page=1&page_size=1")
    status_filter = client.get("/api/cases?status=INCOMPLETE")
    detail = client.get("/api/cases/case_2")
    missing = client.get("/api/cases/not-found")

    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["case_id"] == "case_2"
    assert status_filter.json()["total"] == 3
    assert detail.json()["case"]["email"] == "second@example.com"
    assert detail.json()["result"]["deletion_status"] == "INCOMPLETE"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CASE_NOT_FOUND"


def test_missing_evidence_never_verifies_reported_complete(tmp_path):
    client = make_client(tmp_path)

    response = client.post("/api/audits/run")
    result = client.get("/api/results").json()["items"][0]

    assert response.status_code == 200
    assert response.json()["status_counts"]["INCOMPLETE"] == 1
    assert result["reported_status"] == "COMPLETE"
    assert result["deletion_status"] == "INCOMPLETE"
    assert result["engine_verdict"] == "INCONCLUSIVE"
    assert result["supporting_evidence"] == []
    assert any(
        finding["code"] == "REPORTED_STATUS_UNVERIFIED"
        for finding in result["findings"]
    )
    assert result["evidence_gaps"]
    assert result["steps"]


def test_present_but_unmapped_source_rows_do_not_verify_deletion(tmp_path):
    client = make_client(tmp_path)
    dataset = tmp_path / "dataset"
    for name in (
        "user_identities.csv",
        "user_audit_log.csv",
        "system_activity.csv",
        "deletion_rules.csv",
        "evidence_files.csv",
    ):
        (dataset / name).write_text("unknown_column\nsome-value\n", encoding="utf-8")
    evidence_dir = dataset / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "record.txt").write_text("unmapped content", encoding="utf-8")

    dashboard = client.get("/api/dashboard").json()
    client.post("/api/audits/run")
    result = client.get("/api/results").json()["items"][0]

    assert dashboard["audit_inputs_ready"] is True
    assert dashboard["decision_checks_available"] is False
    assert dashboard["audit_ready"] is False
    assert result["deletion_status"] == "INCOMPLETE"
    assert any(
        gap["code"] == "EVIDENCE_SCHEMA_UNMAPPED"
        for gap in result["evidence_gaps"]
    )


def test_run_writes_exact_output_schema_and_valid_steps_json(tmp_path):
    client = make_client(tmp_path)

    client.post("/api/audits/run")
    csv_response = client.get("/api/results/export.csv")

    assert csv_response.status_code == 200
    reader = csv.DictReader(io.StringIO(csv_response.text))
    assert tuple(reader.fieldnames) == RESULT_COLUMNS
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["case_id"] == "case_1"
    assert rows[0]["deletion_status"] == "INCOMPLETE"
    assert isinstance(json.loads(rows[0]["steps_json"]), list)
    written = tmp_path / "dataset" / "output.csv"
    with written.open(encoding="utf-8", newline="") as stream:
        assert tuple(csv.DictReader(stream).fieldnames) == RESULT_COLUMNS


def test_run_and_export_require_imported_requests_and_audit(tmp_path):
    client = make_client(tmp_path, with_requests=False)

    run_response = client.post("/api/audits/run")
    export_response = client.get("/api/results/export.csv")
    results_response = client.get("/api/results")

    assert run_response.status_code == 409
    assert export_response.status_code == 409
    assert results_response.status_code == 409
    assert run_response.json()["error"]["code"] == "NO_REQUESTS"
    assert export_response.json()["error"]["code"] == "AUDIT_NOT_RUN"
