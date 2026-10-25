
import pytest
from pydantic import ValidationError

from assurance_engine.ai.schemas import (
    ExtractedFact,
    ExtractionRequest,
    ExtractionResponse,
)


def test_valid_extraction_request():
    request = ExtractionRequest(
        claim="The service is operational",
        source_id="status-page",
        source_text="Service status: operational",
    )

    assert request.source_id == "status-page"


def test_blank_source_text_is_rejected():
    with pytest.raises(ValidationError):
        ExtractionRequest(
            claim="Service is operational",
            source_id="status-page",
            source_text="   ",
        )


def test_valid_extracted_fact():
    fact = ExtractedFact(
        field_name="status",
        value="operational",
        source_id="status-page",
        supporting_quote="Service status: operational",
        confidence=0.95,
    )

    assert fact.value == "operational"


def test_confidence_out_of_range_is_rejected():
    with pytest.raises(ValidationError):
        ExtractedFact(
            field_name="status",
            value="operational",
            source_id="status-page",
            supporting_quote="Service status: operational",
            confidence=1.5,
        )


def test_trust_escalation_field_is_rejected():
    with pytest.raises(ValidationError):
        ExtractedFact(
            field_name="status",
            value="operational",
            source_id="status-page",
            supporting_quote="Service status: operational",
            confidence=0.95,
            trusted=True,
        )


def test_final_verdict_field_is_rejected():
    with pytest.raises(ValidationError):
        ExtractionResponse(
            facts=[],
            verdict="VERIFIED",
        )


def test_insufficient_information_is_representable():
    response = ExtractionResponse(
        facts=[],
        status="insufficient_information",
        limitations=["The supplied source contains no status."],
    )

    assert response.facts == []
    assert response.status == "insufficient_information"


def test_source_reference_is_required():
    with pytest.raises(ValidationError):
        ExtractedFact(
            field_name="status",
            value="operational",
            supporting_quote="Service status: operational",
            confidence=0.9,
        )
