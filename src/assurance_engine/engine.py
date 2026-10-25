"""Deterministic evidence verification engine."""

from collections.abc import Sequence
from datetime import datetime, timezone

from assurance_engine.schemas import (
    Evidence,
    Finding,
    VerificationPolicy,
    VerificationResult,
    Verdict,
)


def _same_value(left: object, right: object) -> bool:
    """Compare values recursively without coercing types."""

    if type(left) is not type(right):
        return False

    if isinstance(left, dict):
        return (
            left.keys() == right.keys()
            and all(
                _same_value(left[key], right[key])
                for key in left
            )
        )

    if isinstance(left, (list, tuple)):
        return (
            len(left) == len(right)
            and all(
                _same_value(a, b)
                for a, b in zip(left, right)
            )
        )

    return bool(left == right)


def verify(
    claim: str,
    evidence: Sequence[Evidence],
    policy: VerificationPolicy,
    *,
    checked_at: datetime | None = None,
) -> VerificationResult:
    """Verify a claim against evidence and an explicit policy.

    VERIFIED:
        Eligible evidence matches the expected value.

    FAILED:
        Trusted, non-conflicting evidence contradicts the expected value.

    INCONCLUSIVE:
        Evidence is missing, conflicting, insufficient, or untrusted.
    """

    # 1. Validate inputs.
    if not isinstance(claim, str) or not claim.strip():
        raise ValueError("claim must be a non-empty string")

    if not isinstance(policy, VerificationPolicy):
        raise TypeError("policy must be a VerificationPolicy")

    if isinstance(evidence, (str, bytes)) or not isinstance(
        evidence, Sequence
    ):
        raise TypeError(
            "evidence must be a sequence of Evidence objects"
        )

    if any(not isinstance(item, Evidence) for item in evidence):
        raise TypeError(
            "Every evidence item must be an Evidence object"
        )

    evidence_ids = [item.evidence_id for item in evidence]

    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("Evidence IDs must be unique")

    timestamp = (
        checked_at
        if checked_at is not None
        else datetime.now(timezone.utc)
    )

    if (
        not isinstance(timestamp, datetime)
        or timestamp.tzinfo is None
        or timestamp.utcoffset() is None
    ):
        raise ValueError("checked_at must be a timezone-aware datetime")

    findings: list[Finding] = []

    # 2. Apply the evidence trust policy.
    # 2. Apply the evidence freshness policy.
    if policy.max_age_seconds is None:
        fresh_evidence = list(evidence)
    else:
        fresh_evidence = []
        stale_ids = []
        future_ids = []

        for item in evidence:
            age_seconds = (
                timestamp - item.observed_at
            ).total_seconds()

            if age_seconds < 0:
                future_ids.append(item.evidence_id)
            elif age_seconds > policy.max_age_seconds:
                stale_ids.append(item.evidence_id)
            else:
                fresh_evidence.append(item)

        if stale_ids:
            findings.append(
                Finding(
                    code="STALE_EVIDENCE",
                    message=(
                        "Evidence exceeds the maximum permitted age "
                        f"of {policy.max_age_seconds} seconds."
                    ),
                    evidence_ids=sorted(stale_ids),
                )
            )

        if future_ids:
            findings.append(
                Finding(
                    code="FUTURE_DATED_EVIDENCE",
                    message=(
                        "Evidence was observed after the verification "
                        "timestamp and cannot be used."
                    ),
                    evidence_ids=sorted(future_ids),
                )
            )

    # 3. Apply the evidence trust policy.
    untrusted = [
        item for item in fresh_evidence
        if not item.trusted
    ]

    if policy.require_trusted_evidence:
        eligible = [
            item for item in fresh_evidence
            if item.trusted
        ]

        if untrusted:
            findings.append(
                Finding(
                    code="UNTRUSTED_EVIDENCE",
                    message=(
                        "Untrusted evidence cannot satisfy this policy."
                    ),
                    evidence_ids=sorted(
                        item.evidence_id for item in untrusted
                    ),
                )
            )
    else:
        eligible = list(fresh_evidence)

    # 3. Every required source must provide the claim field itself.
    if policy.claim_field is not None:
        claim_sources = {
            item.source
            for item in eligible
            if policy.claim_field in item.payload
        }
    else:
        claim_sources = set()

    missing_sources = sorted(
        set(policy.required_sources) - claim_sources
    )

    if missing_sources:
        findings.append(
            Finding(
                code="MISSING_REQUIRED_SOURCE",
                message=(
                    f"Missing required sources: {missing_sources}"
                ),
            )
        )

    # 4. Check required payload fields.

    # Every required payload field must exist in the same
    # evidence record that contains the claim field.
    missing_fields = sorted(
        field
        for field in set(policy.required_payload_fields)
        if not any(
            policy.claim_field in item.payload
            and field in item.payload
            for item in eligible
        )
    )

    if missing_fields:
        findings.append(
            Finding(
                code="MISSING_REQUIRED_FIELD",
                message=(
                    "Required payload fields are missing from "
                    "claim-bearing evidence: "
                    f"{missing_fields}"
                ),
            )
        )

    # 5. Require an explicitly defined claim field.
    if policy.claim_field is None:
        findings.append(
            Finding(
                code="CLAIM_CONDITION_UNDEFINED",
                message=(
                    "Set claim_field and expected_value in the policy "
                    "to define the verification condition."
                ),
            )
        )

        return VerificationResult(
            claim=claim,
            verdict=Verdict.INCONCLUSIVE,
            findings=findings,
            checked_at=timestamp,
        )

    # 6. Do not treat an omitted expected_value as an explicit None.
    if "expected_value" not in policy.model_fields_set:
        findings.append(
            Finding(
                code="CLAIM_EXPECTED_VALUE_UNDEFINED",
                message=(
                    "The policy must explicitly define expected_value."
                ),
            )
        )

        return VerificationResult(
            claim=claim,
            verdict=Verdict.INCONCLUSIVE,
            findings=findings,
            checked_at=timestamp,
        )

    # 7. Find eligible evidence containing the claim field.
    field_evidence = [
        item
        for item in eligible
        if policy.claim_field in item.payload
    ]

    if not field_evidence:
        findings.append(
            Finding(
                code="CLAIM_EVIDENCE_MISSING",
                message=(
                    f"No eligible evidence contains "
                    f"'{policy.claim_field}'."
                ),
            )
        )

        return VerificationResult(
            claim=claim,
            verdict=Verdict.INCONCLUSIVE,
            findings=findings,
            checked_at=timestamp,
        )

    # 8. Detect disagreement between eligible evidence records.
    values = [
        item.payload[policy.claim_field]
        for item in field_evidence
    ]

    first_value = values[0]

    if any(
        not _same_value(value, first_value)
        for value in values[1:]
    ):
        findings.append(
            Finding(
                code="CONFLICTING_EVIDENCE",
                message=(
                    f"Eligible evidence disagrees on "
                    f"'{policy.claim_field}'."
                ),
                evidence_ids=sorted(
                    item.evidence_id for item in field_evidence
                ),
            )
        )

        return VerificationResult(
            claim=claim,
            verdict=Verdict.INCONCLUSIVE,
            findings=findings,
            checked_at=timestamp,
        )

    # 9. Missing mandatory requirements prevent a conclusive verdict.
    if missing_sources or missing_fields:
        return VerificationResult(
            claim=claim,
            verdict=Verdict.INCONCLUSIVE,
            findings=findings,
            checked_at=timestamp,
        )

    # 10. Check whether the evidence matches the expected value.
    if _same_value(first_value, policy.expected_value):
        findings.append(
            Finding(
                code="CLAIM_MATCHED",
                message="Evidence matches the expected value.",
                evidence_ids=sorted(
                    item.evidence_id for item in field_evidence
                ),
            )
        )

        return VerificationResult(
            claim=claim,
            verdict=Verdict.VERIFIED,
            findings=findings,
            checked_at=timestamp,
        )

    # 11. A contradiction establishes failure only with trusted evidence.
    trusted_field_evidence = [
        item
        for item in field_evidence
        if item.trusted
    ]

    if trusted_field_evidence:
        findings.append(
            Finding(
                code="CLAIM_CONTRADICTED",
                message=(
                    "Trusted evidence contradicts the expected value."
                ),
                evidence_ids=sorted(
                    item.evidence_id
                    for item in trusted_field_evidence
                ),
            )
        )

        return VerificationResult(
            claim=claim,
            verdict=Verdict.FAILED,
            findings=findings,
            checked_at=timestamp,
        )

    # 12. Untrusted contradictory evidence cannot establish failure.
    findings.append(
        Finding(
            code="INSUFFICIENT_TRUST",
            message=(
                "Contradictory evidence is not trusted enough "
                "to establish failure."
            ),
            evidence_ids=sorted(
                item.evidence_id for item in field_evidence
            ),
        )
    )

    return VerificationResult(
        claim=claim,
        verdict=Verdict.INCONCLUSIVE,
        findings=findings,
        checked_at=timestamp,
    )