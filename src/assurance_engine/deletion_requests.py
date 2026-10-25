"""Load and validate supplied deletion-request CSV files."""

import argparse
import csv
import io
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


REQUEST_COLUMNS = (
    "case_id",
    "email",
    "requested_at",
    "reported_status",
    "reported_at",
    "audit_at",
    "request_text",
)

REPORTED_STATUSES = {
    "COMPLETE",
    "PARTIALLY_COMPLETE",
    "NOT_STARTED",
}

AUDIT_DATASET_FILES = (
    "user_identities.csv",
    "user_audit_log.csv",
    "system_activity.csv",
    "deletion_rules.csv",
    "evidence_files.csv",
)

ACCEPTANCE_DATASET_FILES = (
    "sample_deletion_requests.csv",
    "sample_output.csv",
)


class DeletionRequestCSVError(ValueError):
    """Raised when a deletion-request CSV is malformed."""


@dataclass(frozen=True)
class DeletionRequest:
    case_id: str
    email: str
    requested_at: datetime
    reported_status: str
    reported_at: datetime
    audit_at: datetime
    request_text: str


@dataclass(frozen=True)
class RequestIdentityGroup:
    normalized_email: str
    case_ids: tuple[str, ...]
    reported_statuses: tuple[str, ...]


@dataclass(frozen=True)
class RequestSetAnalysis:
    request_count: int
    reported_status_counts: dict[str, int]
    unique_email_count: int
    repeated_email_groups: tuple[RequestIdentityGroup, ...]
    conflicting_reported_status_groups: tuple[RequestIdentityGroup, ...]
    invalid_timeline_case_ids: tuple[str, ...]


def analyze_request_set(
    requests: list[DeletionRequest],
) -> RequestSetAnalysis:
    """Summarize facts present in the request file without treating reports as evidence."""

    by_email: dict[str, list[DeletionRequest]] = defaultdict(list)
    for request in requests:
        by_email[request.email.strip().casefold()].append(request)

    groups = tuple(
        RequestIdentityGroup(
            normalized_email=email,
            case_ids=tuple(
                request.case_id
                for request in sorted(
                    items,
                    key=lambda item: (item.requested_at, item.case_id),
                )
            ),
            reported_statuses=tuple(
                sorted({request.reported_status for request in items})
            ),
        )
        for email, items in sorted(by_email.items())
    )

    return RequestSetAnalysis(
        request_count=len(requests),
        reported_status_counts=dict(
            sorted(Counter(request.reported_status for request in requests).items())
        ),
        unique_email_count=len(by_email),
        repeated_email_groups=tuple(
            group for group in groups if len(group.case_ids) > 1
        ),
        conflicting_reported_status_groups=tuple(
            group for group in groups if len(group.reported_statuses) > 1
        ),
        invalid_timeline_case_ids=tuple(
            sorted(
                request.case_id
                for request in requests
                if not (
                    request.requested_at
                    <= request.reported_at
                    <= request.audit_at
                )
            )
        ),
    )


def _parse_timestamp(value: str, *, row_number: int, column: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DeletionRequestCSVError(
            f"Row {row_number}: {column} must be an ISO 8601 timestamp"
        ) from error

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise DeletionRequestCSVError(
            f"Row {row_number}: {column} must include a timezone"
        )

    return timestamp


def load_deletion_requests(path: str | Path) -> list[DeletionRequest]:
    """Read requests from a CSV with the supplied dataset's exact columns."""

    csv_path = Path(path)

    try:
        source = csv_path.open("r", encoding="utf-8-sig", newline="")
    except OSError as error:
        raise DeletionRequestCSVError(
            f"Cannot read deletion requests at {csv_path}: {error}"
        ) from error

    with source:
        return _load_deletion_requests_from_stream(source, str(csv_path))


def load_deletion_requests_text(
    text: str, *, source_name: str = "uploaded CSV"
) -> list[DeletionRequest]:
    """Validate an uploaded CSV without writing it to the input dataset."""

    return _load_deletion_requests_from_stream(
        io.StringIO(text, newline=""),
        source_name,
    )


def _load_deletion_requests_from_stream(
    source: io.TextIOBase, source_name: str
) -> list[DeletionRequest]:
    reader = csv.DictReader(source)
    if reader.fieldnames is None:
        raise DeletionRequestCSVError(
            f"{source_name} is empty or has no CSV header"
        )
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise DeletionRequestCSVError(
            f"{source_name} contains duplicate column names"
        )
    if tuple(reader.fieldnames) != REQUEST_COLUMNS:
        raise DeletionRequestCSVError(
            f"{source_name} must have columns in this order: "
            f"{','.join(REQUEST_COLUMNS)}"
        )

    requests: list[DeletionRequest] = []
    seen_case_ids: set[str] = set()

    for row_number, row in enumerate(reader, start=2):
        if None in row or any(value is None for value in row.values()):
            raise DeletionRequestCSVError(
                f"Row {row_number}: column count does not match the header"
            )

        values = {column: row[column].strip() for column in REQUEST_COLUMNS}
        for column, value in values.items():
            if not value:
                raise DeletionRequestCSVError(
                    f"Row {row_number}: {column} must not be blank"
                )

        case_id = values["case_id"]
        if case_id in seen_case_ids:
            raise DeletionRequestCSVError(
                f"Row {row_number}: duplicate case_id {case_id!r}"
            )
        seen_case_ids.add(case_id)

        status = values["reported_status"]
        if status not in REPORTED_STATUSES:
            raise DeletionRequestCSVError(
                f"Row {row_number}: unsupported reported_status "
                f"{status!r}"
            )

        requests.append(
            DeletionRequest(
                case_id=case_id,
                email=values["email"],
                requested_at=_parse_timestamp(
                    values["requested_at"],
                    row_number=row_number,
                    column="requested_at",
                ),
                reported_status=status,
                reported_at=_parse_timestamp(
                    values["reported_at"],
                    row_number=row_number,
                    column="reported_at",
                ),
                audit_at=_parse_timestamp(
                    values["audit_at"],
                    row_number=row_number,
                    column="audit_at",
                ),
                request_text=values["request_text"],
            )
        )

    if not requests:
        raise DeletionRequestCSVError(f"{source_name} contains no request rows")

    return requests


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and summarize deletion requests. This is not a "
            "deletion audit."
        )
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        type=Path,
        default=Path("dataset") / "deletion_requests.csv",
        help="CSV path (default: dataset/deletion_requests.csv)",
    )
    args = parser.parse_args(argv)

    try:
        requests = load_deletion_requests(args.csv_path)
    except DeletionRequestCSVError as error:
        print(f"Request CSV validation failed: {error}", file=sys.stderr)
        return 2

    analysis = analyze_request_set(requests)
    print(
        f"Validated {analysis.request_count} deletion requests "
        f"from {args.csv_path}."
    )
    print(f"Reported-status counts (unverified): {analysis.reported_status_counts}")
    print(f"Distinct email identifiers (case-insensitive): {analysis.unique_email_count}")
    print(
        "Repeated email identity groups: "
        f"{len(analysis.repeated_email_groups)}"
    )
    for group in analysis.repeated_email_groups:
        print(
            f"  {group.normalized_email}: "
            f"{', '.join(group.case_ids)}"
        )
    print(
        "Requests with requested_at <= reported_at <= audit_at violations: "
        f"{len(analysis.invalid_timeline_case_ids)}"
    )

    dataset_dir = args.csv_path.parent
    missing_audit_files = [
        dataset_dir / name
        for name in AUDIT_DATASET_FILES
        if not (dataset_dir / name).is_file()
    ]
    evidence_dir = dataset_dir / "evidence"
    if not evidence_dir.is_dir():
        missing_audit_files.append(evidence_dir)

    missing_acceptance_files = [
        dataset_dir / name
        for name in ACCEPTANCE_DATASET_FILES
        if not (dataset_dir / name).is_file()
    ]

    if missing_audit_files:
        print("Deletion audit blocked; required audit inputs are missing:")
        for missing_path in missing_audit_files:
            print(f"  {missing_path}")
    if missing_acceptance_files:
        print(
            "Acceptance comparison unavailable; sample files are missing:"
        )
        for missing_path in missing_acceptance_files:
            print(f"  {missing_path}")
    print(
        "No output.csv was generated. Reported statuses and timestamps are "
        "request-file claims, not deletion evidence."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
