
"""Validated contracts for untrusted LLM extraction output."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExtractionRequest(BaseModel):
    """Input supplied to an extraction provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim: str = Field(min_length=1, max_length=4_000)
    source_id: str = Field(min_length=1, max_length=200)
    source_text: str = Field(min_length=1, max_length=50_000)

    @field_validator("claim", "source_id", "source_text")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value


class ExtractedFact(BaseModel):
    """A candidate fact extracted from supplied source material.

    This model intentionally has no trusted flag and no final verdict.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    field_name: str = Field(min_length=1, max_length=200)
    value: str | int | float | bool | None
    source_id: str = Field(min_length=1, max_length=200)
    supporting_quote: str = Field(min_length=1, max_length=2_000)
    observation_time: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("field_name", "source_id", "supporting_quote")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value


class ExtractionResponse(BaseModel):
    """Structured output from an untrusted extraction provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    facts: list[ExtractedFact] = Field(max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=50)
    status: Literal["ok", "insufficient_information"] = "ok"
