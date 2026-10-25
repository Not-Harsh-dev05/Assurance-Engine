
"""Ground LLM-extracted facts in supplied source material."""

from datetime import datetime

from assurance_engine.ai.schemas import (
    ExtractedFact,
    ExtractionRequest,
)
from assurance_engine.schemas import Evidence


class GroundingError(ValueError):
    """Raised when extracted facts cannot be grounded safely."""


def fact_to_evidence(
    fact: ExtractedFact,
    request: ExtractionRequest,
    *,
    observed_at: datetime | None = None,
) -> Evidence:
    """Convert a grounded extracted fact into untrusted evidence.

    Quote presence does not establish semantic entailment or source
    authenticity. The resulting evidence is always untrusted.
    """
    if not isinstance(fact, ExtractedFact):
        raise GroundingError("fact must be an ExtractedFact.")

    if not isinstance(request, ExtractionRequest):
        raise GroundingError("request must be an ExtractionRequest.")

    if fact.source_id != request.source_id:
        raise GroundingError(
            "Extracted fact references a different source."
        )

    if not fact.supporting_quote.strip():
        raise GroundingError("Supporting quote must not be empty.")

    if fact.supporting_quote not in request.source_text:
        raise GroundingError(
            "Supporting quote does not occur in the supplied source."
        )

    if observed_at is not None:
        timestamp = observed_at
    else:
        if not fact.observation_time:
            raise GroundingError(
                "Original observation time is required to create evidence."
            )

        try:
            timestamp = datetime.fromisoformat(fact.observation_time)
        except (TypeError, ValueError) as exc:
            raise GroundingError(
                "Observation time must be a valid ISO 8601 timestamp."
            ) from exc

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise GroundingError(
            "Observation timestamp must be timezone-aware."
        )

    return Evidence(
        evidence_id=f"llm:{request.source_id}:{fact.field_name}",
        source=request.source_id,
        observed_at=timestamp,
        trusted=False,
        payload={fact.field_name: fact.value},
    )
