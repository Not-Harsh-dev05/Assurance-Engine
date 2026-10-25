
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class VerificationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=1)
    required_sources: list[str] = Field(default_factory=list)
    required_payload_fields: list[str] = Field(default_factory=list)
    require_trusted_evidence: bool = True


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
