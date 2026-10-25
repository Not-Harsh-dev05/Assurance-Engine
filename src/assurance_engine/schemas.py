from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Verdict(str, Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    observed_at: datetime
    trusted: bool = False
    payload: dict[str, Any]

    @field_validator("evidence_id", "source")
    @classmethod
    def validate_nonblank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at_timezone(
        cls, value: datetime
    ) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value


class VerificationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=1)
    required_sources: list[str] = Field(default_factory=list)
    required_payload_fields: list[str] = Field(default_factory=list)
    require_trusted_evidence: bool = True
    max_age_seconds: int | None = Field(default=None, ge=0)

    # The field and value used to evaluate the claim.
    claim_field: str | None = None
    expected_value: Any = None

    @field_validator("policy_id", "claim_field")
    @classmethod
    def validate_policy_strings(
        cls, value: str | None
    ) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Value cannot be blank")
        return value

    @field_validator("required_sources", "required_payload_fields")
    @classmethod
    def validate_required_items(
        cls, values: list[str]
    ) -> list[str]:
        if any(not item.strip() for item in values):
            raise ValueError("Required values cannot be blank")
        return values


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    evidence_ids: list[str] = Field(default_factory=list)


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    verdict: Verdict
    findings: list[Finding] = Field(default_factory=list)
    checked_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @field_validator("checked_at")
    @classmethod
    def validate_checked_at_timezone(
        cls, value: datetime
    ) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        return value
