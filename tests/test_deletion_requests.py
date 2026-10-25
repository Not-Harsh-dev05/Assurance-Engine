import csv
from datetime import datetime, timezone

import pytest

from assurance_engine.deletion_requests import (
    REQUEST_COLUMNS,
    DeletionRequestCSVError,
    analyze_request_set,
    load_deletion_requests,
    main,
)


def write_csv(path, rows, *, columns=REQUEST_COLUMNS):
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def valid_row(**updates):
    row = {
        "case_id": "case_1",
        "email": "user@example.com",
        "requested_at": "2026-01-01T10:00:00Z",
        "reported_status": "COMPLETE",
        "reported_at": "2026-01-02T10:00:00Z",
        "audit_at": "2026-01-03T10:00:00Z",
        "request_text": "Please delete my account.",
    }
    row.update(updates)
    return row


def test_loads_valid_request_csv(tmp_path):
    path = tmp_path / "requests.csv"
    write_csv(path, [valid_row()])

    requests = load_deletion_requests(path)

    assert len(requests) == 1
    assert requests[0].case_id == "case_1"
    assert requests[0].email == "user@example.com"
    assert requests[0].reported_status == "COMPLETE"
    assert requests[0].requested_at == datetime(
        2026, 1, 1, 10, tzinfo=timezone.utc
    )


def test_rejects_unexpected_or_reordered_columns(tmp_path):
    path = tmp_path / "requests.csv"
    write_csv(path, [valid_row()], columns=tuple(reversed(REQUEST_COLUMNS)))

    with pytest.raises(DeletionRequestCSVError, match="must have columns"):
        load_deletion_requests(path)


def test_rejects_blank_required_values(tmp_path):
    path = tmp_path / "requests.csv"
    write_csv(path, [valid_row(email=" ")])

    with pytest.raises(DeletionRequestCSVError, match="email must not be blank"):
        load_deletion_requests(path)


def test_rejects_invalid_timestamp(tmp_path):
    path = tmp_path / "requests.csv"
    write_csv(path, [valid_row(requested_at="not-a-timestamp")])

    with pytest.raises(
        DeletionRequestCSVError,
        match="requested_at must be an ISO 8601 timestamp",
    ):
        load_deletion_requests(path)


def test_rejects_timestamp_without_timezone(tmp_path):
    path = tmp_path / "requests.csv"
    write_csv(path, [valid_row(audit_at="2026-01-03T10:00:00")])

    with pytest.raises(
        DeletionRequestCSVError,
        match="audit_at must include a timezone",
    ):
        load_deletion_requests(path)


def test_rejects_unknown_reported_status(tmp_path):
    path = tmp_path / "requests.csv"
    write_csv(path, [valid_row(reported_status="IN_PROGRESS")])

    with pytest.raises(
        DeletionRequestCSVError,
        match="unsupported reported_status",
    ):
        load_deletion_requests(path)


def test_rejects_duplicate_case_ids(tmp_path):
    path = tmp_path / "requests.csv"
    write_csv(path, [valid_row(), valid_row(email="other@example.com")])

    with pytest.raises(DeletionRequestCSVError, match="duplicate case_id"):
        load_deletion_requests(path)


def test_rejects_wrong_number_of_csv_fields(tmp_path):
    path = tmp_path / "requests.csv"
    path.write_text(
        ",".join(REQUEST_COLUMNS) + "\n"
        "case_1,user@example.com,2026-01-01T10:00:00Z,COMPLETE,"
        "2026-01-02T10:00:00Z,2026-01-03T10:00:00Z,request,extra\n",
        encoding="utf-8",
    )

    with pytest.raises(
        DeletionRequestCSVError,
        match="column count does not match",
    ):
        load_deletion_requests(path)


def test_cli_validates_requests_without_claiming_audit_completion(tmp_path, capsys):
    path = tmp_path / "requests.csv"
    write_csv(path, [valid_row()])

    assert main([str(path)]) == 0
    output = capsys.readouterr().out
    assert "Validated 1 deletion requests" in output
    assert "Deletion audit blocked" in output
    assert "No output.csv was generated" in output


def test_analysis_correlates_case_insensitive_repeated_emails(tmp_path):
    path = tmp_path / "requests.csv"
    write_csv(
        path,
        [
            valid_row(case_id="case_1", email="User@example.com"),
            valid_row(
                case_id="case_2",
                email="user@EXAMPLE.com",
                requested_at="2026-01-04T10:00:00Z",
                reported_at="2026-01-05T10:00:00Z",
                audit_at="2026-01-06T10:00:00Z",
                reported_status="NOT_STARTED",
            ),
        ],
    )

    analysis = analyze_request_set(load_deletion_requests(path))

    assert analysis.request_count == 2
    assert analysis.unique_email_count == 1
    assert analysis.repeated_email_groups[0].case_ids == (
        "case_1",
        "case_2",
    )
    assert analysis.conflicting_reported_status_groups[0].reported_statuses == (
        "COMPLETE",
        "NOT_STARTED",
    )
    assert analysis.invalid_timeline_case_ids == ()


def test_analysis_reports_invalid_timeline_without_rewriting_input(tmp_path):
    path = tmp_path / "requests.csv"
    write_csv(
        path,
        [
            valid_row(
                requested_at="2026-01-04T10:00:00Z",
                reported_at="2026-01-02T10:00:00Z",
            )
        ],
    )

    analysis = analyze_request_set(load_deletion_requests(path))

    assert analysis.invalid_timeline_case_ids == ("case_1",)


def test_supplied_request_dataset_is_valid():
    requests = load_deletion_requests("dataset/deletion_requests.csv")

    assert len(requests) == 518
    assert requests[0].case_id == "case_33"
    assert requests[-1].case_id == "case_550"


def test_supplied_request_dataset_analysis():
    analysis = analyze_request_set(
        load_deletion_requests("dataset/deletion_requests.csv")
    )

    assert analysis.request_count == 518
    assert analysis.reported_status_counts == {
        "COMPLETE": 254,
        "NOT_STARTED": 112,
        "PARTIALLY_COMPLETE": 152,
    }
    assert analysis.unique_email_count == 517
    assert len(analysis.repeated_email_groups) == 1
    assert analysis.repeated_email_groups[0].case_ids == (
        "case_52",
        "case_33",
    )
    assert analysis.conflicting_reported_status_groups == ()
    assert analysis.invalid_timeline_case_ids == ()
