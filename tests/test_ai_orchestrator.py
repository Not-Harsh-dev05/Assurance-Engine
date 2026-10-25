
import asyncio
from datetime import datetime, timezone

import pytest

from assurance_engine.ai.orchestrator import verify_with_llm
from assurance_engine.ai.provider import FakeLLMProvider
from assurance_engine.ai.schemas import (
    ExtractedFact,
    ExtractionRequest,
    ExtractionResponse,
)
from assurance_engine.schemas import (
    VerificationPolicy,
    Verdict,
)


CHECKED_AT = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def extraction_request():
    return ExtractionRequest(
        claim="The service is operational",
        source_id="status-page",
        source_text="Service status: operational",
    )


@pytest.fixture
def extraction_response():
    return ExtractionResponse(
        facts=[
            ExtractedFact(
                field_name="status",
                value="operational",
                source_id="status-page",
                supporting_quote="Service status: operational",
                observation_time="2026-10-25T10:00:00+00:00",
                confidence=0.95,
            )
        ]
    )


@pytest.fixture
def policy():
    return VerificationPolicy(
        policy_id="service-status",
        claim_field="status",
        expected_value="operational",
    )


@pytest.mark.asyncio
async def test_default_trust_policy_rejects_llm_evidence(
    extraction_request, extraction_response, policy
):
    result = await verify_with_llm(
        extraction_request.claim,
        extraction_request,
        policy,
        FakeLLMProvider(response=extraction_response),
        checked_at=CHECKED_AT,
    )

    assert result.verdict == Verdict.INCONCLUSIVE
    assert any(
        finding.code == "UNTRUSTED_EVIDENCE"
        for finding in result.findings
    )


@pytest.mark.asyncio
async def test_explicit_policy_allows_engine_to_evaluate_untrusted_evidence(
    extraction_request, extraction_response, policy
):
    permissive_policy = policy.model_copy(
        update={"require_trusted_evidence": False}
    )

    result = await verify_with_llm(
        extraction_request.claim,
        extraction_request,
        permissive_policy,
        FakeLLMProvider(response=extraction_response),
        checked_at=CHECKED_AT,
    )

    # The engine evaluates the evidence under the explicit policy.
    assert result.verdict == Verdict.VERIFIED


@pytest.mark.asyncio
async def test_provider_failure_returns_inconclusive_result(
    extraction_request, policy
):
    provider = FakeLLMProvider(
        error=RuntimeError("simulated provider failure")
    )

    result = await verify_with_llm(
        extraction_request.claim,
        extraction_request,
        policy,
        provider,
        checked_at=CHECKED_AT,
    )

    assert result.verdict == Verdict.INCONCLUSIVE
    assert any(
        finding.code == "AI_EXTRACTION_FAILED"
        for finding in result.findings
    )


@pytest.mark.asyncio
async def test_empty_extraction_returns_inconclusive_result(
    extraction_request, policy
):
    provider = FakeLLMProvider(
        response=ExtractionResponse(
            facts=[],
            status="insufficient_information",
        )
    )

    result = await verify_with_llm(
        extraction_request.claim,
        extraction_request,
        policy,
        provider,
        checked_at=CHECKED_AT,
    )

    assert result.verdict == Verdict.INCONCLUSIVE
    assert any(
        finding.code == "AI_INSUFFICIENT_INFORMATION"
        for finding in result.findings
    )


@pytest.mark.asyncio
async def test_fabricated_quote_rejects_entire_extraction_batch(
    extraction_request, extraction_response, policy
):
    fabricated_fact = ExtractedFact(
        field_name="status",
        value="operational",
        source_id="status-page",
        supporting_quote="Everything is healthy",
        observation_time="2026-10-25T10:00:00+00:00",
        confidence=0.99,
    )

    response = ExtractionResponse(
        facts=[*extraction_response.facts, fabricated_fact]
    )

    result = await verify_with_llm(
        extraction_request.claim,
        extraction_request,
        policy,
        FakeLLMProvider(response=response),
        checked_at=CHECKED_AT,
    )

    assert result.verdict == Verdict.INCONCLUSIVE
    assert any(
        finding.code == "AI_GROUNDING_FAILED"
        for finding in result.findings
    )


@pytest.mark.asyncio
async def test_claim_mismatch_does_not_call_provider(
    extraction_request, policy
):
    provider = FakeLLMProvider()

    result = await verify_with_llm(
        "A different claim",
        extraction_request,
        policy,
        provider,
        checked_at=CHECKED_AT,
    )

    assert result.verdict == Verdict.INCONCLUSIVE
    assert provider.requests == []
    assert any(
        finding.code == "AI_REQUEST_CLAIM_MISMATCH"
        for finding in result.findings
    )


@pytest.mark.asyncio
async def test_provider_timeout_fails_closed(extraction_request, policy):
    class SlowProvider:
        async def extract(self, request):
            await asyncio.sleep(0.1)
            return ExtractionResponse(facts=[])

    result = await verify_with_llm(
        extraction_request.claim,
        extraction_request,
        policy,
        SlowProvider(),
        timeout_seconds=0.001,
        checked_at=CHECKED_AT,
    )

    assert result.verdict == Verdict.INCONCLUSIVE
    assert any(
        finding.code == "AI_EXTRACTION_FAILED"
        for finding in result.findings
    )

@pytest.mark.asyncio
async def test_successful_extraction_passes_evidence_to_engine(
    extraction_request, extraction_response, policy
):
    provider = FakeLLMProvider(response=extraction_response)

    permissive_policy = policy.model_copy(
        update={"require_trusted_evidence": False}
    )

    result = await verify_with_llm(
        extraction_request.claim,
        extraction_request,
        permissive_policy,
        provider,
        checked_at=CHECKED_AT,
    )

    assert len(provider.requests) == 1
    assert result.claim == extraction_request.claim
    assert result.verdict == Verdict.VERIFIED

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "timeout_seconds",
    [
        0,
        -1,
        float("nan"),
        float("inf"),
        float("-inf"),
        True,
        False,
    ],
)
async def test_invalid_timeout_is_rejected(
    timeout_seconds, extraction_request, policy
):
    with pytest.raises(
        ValueError,
        match="finite number",
    ):
        await verify_with_llm(
            claim=extraction_request.claim,
            request=extraction_request,
            policy=policy,
            provider=FakeLLMProvider(),
            timeout_seconds=timeout_seconds,
        )


@pytest.mark.asyncio
async def test_unrelated_extracted_field_rejects_entire_batch(
    extraction_request, policy
):
    response = ExtractionResponse(
        facts=[
            ExtractedFact(
                field_name="status",
                value="operational",
                source_id="status-page",
                supporting_quote="Service status: operational",
                observation_time="2026-10-25T10:00:00+00:00",
                confidence=0.95,
            ),
            ExtractedFact(
                field_name="admin",
                value=True,
                source_id="status-page",
                supporting_quote="Service status: operational",
                observation_time="2026-10-25T10:00:00+00:00",
                confidence=0.99,
            ),
        ]
    )

    permissive_policy = policy.model_copy(
        update={"require_trusted_evidence": False}
    )

    result = await verify_with_llm(
        extraction_request.claim,
        extraction_request,
        permissive_policy,
        FakeLLMProvider(response=response),
        checked_at=CHECKED_AT,
    )

    assert result.verdict == Verdict.INCONCLUSIVE
    assert any(
        finding.code == "AI_GROUNDING_FAILED"
        for finding in result.findings
    )
