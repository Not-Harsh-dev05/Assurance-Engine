
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from assurance_engine import (
    Evidence,
    Finding,
    VerificationPolicy,
    VerificationResult,
    Verdict,
)


def test_evidence_can_be_created():
    evidence = Evidence(
        evidence_id="ev-001",
        source="authentication_service",
        observed_at=datetime.now(timezone.utc),
        payload={"user_id": "user-123", "authenticated": True},
    )

    assert evidence.evidence_id == "ev-001"
    assert evidence.trusted is False


def test_evidence_rejects_empty_id():
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="",
            source="auth",
            observed_at=datetime.now(timezone.utc),
            payload={},
        )


def test_evidence_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="ev-002",
            source="auth",
            observed_at=datetime.now(timezone.utc),
            payload={},
            fabricated=True,
        )


def test_policy_defaults_to_requiring_trusted_evidence():
    policy = VerificationPolicy(policy_id="auth-policy")

    assert policy.require_trusted_evidence is True
    assert policy.required_sources == []


def test_result_uses_standardized_verdict():
    result = VerificationResult(
        claim="User authentication succeeded",
        verdict=Verdict.INCONCLUSIVE,
        findings=[
            Finding(
                code="MISSING_EVIDENCE",
                message="No trusted authentication evidence supplied",
            )
        ],
    )

    assert result.verdict == Verdict.INCONCLUSIVE
    assert result.findings[0].evidence_ids == []


def test_verdict_rejects_invalid_values():
    with pytest.raises(ValidationError):
        VerificationResult(
            claim="Authentication succeeded",
            verdict="MAYBE",
        )
