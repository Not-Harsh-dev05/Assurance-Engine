
from datetime import datetime, timezone

import pytest

from assurance_engine.ai.grounding import (
    GroundingError,
    fact_to_evidence,
)
from assurance_engine.ai.schemas import (
    ExtractedFact,
    ExtractionRequest,
)


@pytest.fixture
def extraction_request():
    return ExtractionRequest(
        claim="The service is operational",
        source_id="status-page",
        source_text="Service status: operational",
    )


@pytest.fixture
def extracted_fact():
    return ExtractedFact(
        field_name="status",
        value="operational",
        source_id="status-page",
        supporting_quote="Service status: operational",
        confidence=0.95,
        observation_time="2026-10-25T10:00:00+00:00",
    )


def test_valid_fact_becomes_untrusted_evidence(
    extraction_request, extracted_fact
):
    evidence = fact_to_evidence(extracted_fact, extraction_request)

    assert evidence.source == "status-page"
    assert evidence.payload == {"status": "operational"}
    assert evidence.trusted is False
    assert evidence.observed_at == datetime(
        2026, 10, 25, 10, 0, tzinfo=timezone.utc
    )


def test_wrong_source_reference_is_rejected(
    extraction_request, extracted_fact
):
    wrong_source = extracted_fact.model_copy(
        update={"source_id": "unknown-source"}
    )

    with pytest.raises(GroundingError, match="different source"):
        fact_to_evidence(wrong_source, extraction_request)


def test_fabricated_quote_is_rejected(
    extraction_request, extracted_fact
):
    fabricated = extracted_fact.model_copy(
        update={"supporting_quote": "The database is healthy"}
    )

    with pytest.raises(GroundingError, match="does not occur"):
        fact_to_evidence(fabricated, extraction_request)


def test_missing_observation_time_is_rejected(extraction_request):
    fact = ExtractedFact(
        field_name="status",
        value="operational",
        source_id="status-page",
        supporting_quote="Service status: operational",
        confidence=0.95,
    )

    with pytest.raises(GroundingError, match="observation time"):
        fact_to_evidence(fact, extraction_request)


def test_naive_observation_time_is_rejected(extraction_request):
    fact = ExtractedFact(
        field_name="status",
        value="operational",
        source_id="status-page",
        supporting_quote="Service status: operational",
        confidence=0.95,
        observation_time="2026-10-25T10:00:00",
    )

    with pytest.raises(GroundingError, match="timezone-aware"):
        fact_to_evidence(fact, extraction_request)


def test_explicit_observation_time_is_used(
    extraction_request, extracted_fact
):
    timestamp = datetime(2026, 10, 24, 8, 0, tzinfo=timezone.utc)

    evidence = fact_to_evidence(
        extracted_fact,
        extraction_request,
        observed_at=timestamp,
    )

    assert evidence.observed_at == timestamp
    assert evidence.trusted is False

def test_invalid_observation_timestamp_raises_grounding_error(
    extraction_request, extracted_fact
):
    invalid_fact = extracted_fact.model_copy(
        update={"observation_time": "not-a-timestamp"}
    )

    with pytest.raises(GroundingError, match="valid ISO 8601"):
        fact_to_evidence(invalid_fact, extraction_request)


def test_empty_supporting_quote_is_rejected(
    extraction_request, extracted_fact
):
    invalid_fact = extracted_fact.model_copy(
        update={"supporting_quote": "   "}
    )

    with pytest.raises(GroundingError, match="must not be empty"):
        fact_to_evidence(invalid_fact, extraction_request)


def test_naive_timestamp_override_is_rejected(
    extraction_request, extracted_fact
):
    naive_timestamp = datetime(2026, 10, 25, 10, 0)

    with pytest.raises(GroundingError, match="timezone-aware"):
        fact_to_evidence(
            extracted_fact,
            extraction_request,
            observed_at=naive_timestamp,
        )
