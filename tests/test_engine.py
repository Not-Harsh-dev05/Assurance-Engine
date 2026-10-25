from datetime import datetime, timezone
from datetime import timedelta
import pytest

from assurance_engine import (
    Evidence,
    VerificationPolicy,
    Verdict,
    verify,
)


NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)



def make_evidence(
    evidence_id="ev-1",
    *,
    value="approved",
    trusted=True,
    source="registry",
    payload=None,
    observed_at=None,
):
    return Evidence(
        evidence_id=evidence_id,
        source=source,
        observed_at=observed_at if observed_at is not None else NOW,
        trusted=trusted,
        payload=payload if payload is not None else {"status": value},
    )


def make_policy(**overrides):
    values = {
        "policy_id": "policy-1",
        "claim_field": "status",
        "expected_value": "approved",
        "required_sources": ["registry"],
        "required_payload_fields": ["status"],
        "require_trusted_evidence": True,
    }
    values.update(overrides)
    return VerificationPolicy(**values)


def test_trusted_matching_evidence_is_verified():
    result = verify(
        "Application is approved",
        [make_evidence()],
        make_policy(),
        checked_at=NOW,
    )
    assert result.verdict == Verdict.VERIFIED


def test_missing_evidence_is_inconclusive():
    result = verify("Application is approved", [], make_policy())
    assert result.verdict == Verdict.INCONCLUSIVE


def test_missing_required_field_is_inconclusive():
    evidence = make_evidence(payload={"other": "value"})
    result = verify("Application is approved", [evidence], make_policy())
    assert result.verdict == Verdict.INCONCLUSIVE


def test_untrusted_evidence_cannot_satisfy_trust_required_policy():
    evidence = make_evidence(trusted=False)
    result = verify("Application is approved", [evidence], make_policy())
    assert result.verdict == Verdict.INCONCLUSIVE


def test_trusted_contradiction_is_failed():
    evidence = make_evidence(value="rejected")
    result = verify("Application is approved", [evidence], make_policy())
    assert result.verdict == Verdict.FAILED


def test_conflicting_evidence_is_inconclusive():
    evidence = [
        make_evidence("ev-1", value="approved"),
        make_evidence("ev-2", value="rejected"),
    ]
    result = verify("Application is approved", evidence, make_policy())
    assert result.verdict == Verdict.INCONCLUSIVE


def test_undefined_claim_condition_is_inconclusive():
    policy = make_policy(claim_field=None)
    result = verify("Application is approved", [make_evidence()], policy)
    assert result.verdict == Verdict.INCONCLUSIVE


def test_duplicate_evidence_ids_are_rejected():
    evidence = [
        make_evidence("duplicate"),
        make_evidence("duplicate"),
    ]
    with pytest.raises(ValueError, match="unique"):
        verify("Application is approved", evidence, make_policy())


def test_empty_claim_is_rejected():
    with pytest.raises(ValueError, match="claim"):
        verify("   ", [make_evidence()], make_policy())


def test_naive_observation_timestamp_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        Evidence(
            evidence_id="ev-1",
            source="registry",
            observed_at=datetime(2026, 10, 25, 12, 0),
            trusted=True,
            payload={"status": "approved"},
        )


def test_blank_required_source_is_rejected():
    with pytest.raises(ValueError):
        make_policy(required_sources=["  "])


def test_untrusted_contradiction_cannot_establish_failure():
    evidence = make_evidence(value="rejected", trusted=False)
    policy = make_policy(require_trusted_evidence=False)
    result = verify("Application is approved", [evidence], policy)
    assert result.verdict == Verdict.INCONCLUSIVE


def test_boolean_is_not_equal_to_integer():
    evidence = make_evidence(payload={"status": True})
    policy = make_policy(expected_value=1)
    result = verify("Status is integer one", [evidence], policy)
    assert result.verdict == Verdict.FAILED


def test_missing_expected_value_is_inconclusive():
    policy = VerificationPolicy(
        policy_id="policy-undefined",
        claim_field="status",
        required_sources=[],
        required_payload_fields=["status"],
    )

    evidence = make_evidence(
        payload={"status": None},
    )

    result = verify(
        "Status is approved",
        [evidence],
        policy,
        checked_at=NOW,
    )

    assert result.verdict == Verdict.INCONCLUSIVE
    assert any(
        finding.code == "CLAIM_EXPECTED_VALUE_UNDEFINED"
        for finding in result.findings
    )

def test_nested_boolean_is_not_equal_to_integer():
    evidence = make_evidence(
        payload={"status": {"approved": True}},
    )

    policy = make_policy(
        claim_field="status",
        expected_value={"approved": 1},
    )

    result = verify(
        "Approval status matches",
        [evidence],
        policy,
        checked_at=NOW,
    )

    assert result.verdict == Verdict.FAILED

def test_required_source_must_contain_claim_field():
    evidence = [
        make_evidence(
            evidence_id="registry-1",
            source="registry",
            payload={"name": "Harsh"},
        ),
        make_evidence(
            evidence_id="other-1",
            source="other",
            payload={"status": "approved"},
        ),
    ]

    policy = make_policy(
        required_sources=["registry"],
        required_payload_fields=["status"],
    )

    result = verify(
        "Application is approved",
        evidence,
        policy,
        checked_at=NOW,
    )

    assert result.verdict == Verdict.INCONCLUSIVE
    assert any(
        finding.code == "MISSING_REQUIRED_SOURCE"
        for finding in result.findings
    )

def test_required_fields_must_be_in_claim_bearing_record():
    evidence = [
        make_evidence(
            evidence_id="ev-status",
            source="registry",
            payload={"status": "approved"},
        ),
        make_evidence(
            evidence_id="ev-document",
            source="registry",
            payload={"document_id": "DOC-123"},
        ),
    ]

    policy = make_policy(
        required_sources=["registry"],
        required_payload_fields=["status", "document_id"],
    )

    result = verify(
        "Application is approved",
        evidence,
        policy,
        checked_at=NOW,
    )

    assert result.verdict == Verdict.INCONCLUSIVE
    assert any(
        finding.code == "MISSING_REQUIRED_FIELD"
        for finding in result.findings
    )


def test_evidence_order_does_not_change_verdict():
    evidence_a = make_evidence(
        evidence_id="ev-a",
        source="registry",
        payload={
            "status": "approved",
            "document_id": "DOC-123",
        },
    )
    evidence_b = make_evidence(
        evidence_id="ev-b",
        source="registry",
        payload={
            "status": "approved",
            "document_id": "DOC-456",
        },
    )

    policy = make_policy(
        required_sources=["registry"],
        required_payload_fields=["status"],
    )

    result_forward = verify(
        "Application is approved",
        [evidence_a, evidence_b],
        policy,
        checked_at=NOW,
    )

    result_reverse = verify(
        "Application is approved",
        [evidence_b, evidence_a],
        policy,
        checked_at=NOW,
    )

    assert result_forward.verdict == result_reverse.verdict
    assert result_forward.model_dump() == result_reverse.model_dump()


def test_stale_evidence_is_inconclusive():
    evidence = make_evidence(
        evidence_id="ev-stale",
        source="registry",
        payload={
            "status": "approved",
            "document_id": "DOC-123",
        },
        observed_at=NOW - timedelta(seconds=301),
    )

    policy = make_policy(
        required_sources=["registry"],
        required_payload_fields=["status"],
        max_age_seconds=300,
    )

    result = verify(
        "Application is approved",
        [evidence],
        policy,
        checked_at=NOW,
    )

    assert result.verdict == Verdict.INCONCLUSIVE
    assert any(
        finding.code == "STALE_EVIDENCE"
        for finding in result.findings
    )


def test_fresh_evidence_can_be_verified():
    evidence = make_evidence(
        evidence_id="ev-fresh",
        source="registry",
        payload={
            "status": "approved",
            "document_id": "DOC-123",
        },
        observed_at=NOW - timedelta(seconds=299),
    )

    policy = make_policy(
        required_sources=["registry"],
        required_payload_fields=["status"],
        max_age_seconds=300,
    )

    result = verify(
        "Application is approved",
        [evidence],
        policy,
        checked_at=NOW,
    )

    assert result.verdict == Verdict.VERIFIED


def test_future_dated_evidence_is_inconclusive():
    evidence = make_evidence(
        evidence_id="ev-future",
        source="registry",
        payload={
            "status": "approved",
            "document_id": "DOC-123",
        },
        observed_at=NOW + timedelta(seconds=1),
    )

    policy = make_policy(
        required_sources=["registry"],
        required_payload_fields=["status"],
        max_age_seconds=300,
    )

    result = verify(
        "Application is approved",
        [evidence],
        policy,
        checked_at=NOW,
    )

    assert result.verdict == Verdict.INCONCLUSIVE
    assert any(
        finding.code == "FUTURE_DATED_EVIDENCE"
        for finding in result.findings
    )


def test_freshness_is_disabled_by_default():
    evidence = make_evidence(
        evidence_id="ev-old",
        source="registry",
        payload={
            "status": "approved",
            "document_id": "DOC-123",
        },
        observed_at=NOW - timedelta(days=365),
    )

    policy = make_policy(
        required_sources=["registry"],
        required_payload_fields=["status"],
    )

    result = verify(
        "Application is approved",
        [evidence],
        policy,
        checked_at=NOW,
    )

    assert result.verdict == Verdict.VERIFIED
    assert not any(
        finding.code == "STALE_EVIDENCE"
        for finding in result.findings
    )