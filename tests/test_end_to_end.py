import asyncio
from datetime import datetime, timezone

from assurance_engine.ai.orchestrator import verify_with_llm
from assurance_engine.ai.provider import FakeLLMProvider
from assurance_engine.ai.schemas import (
    ExtractedFact,
    ExtractionRequest,
    ExtractionResponse,
)
from assurance_engine.schemas import VerificationPolicy, Verdict


def test_end_to_end_fake_provider_verification():
    async def run():
        observed_at = datetime.now(timezone.utc)
        source_text = (
            "Service status: operational. "
            f"Observed at: {observed_at.isoformat()}"
        )

        request = ExtractionRequest(
            claim="The service is operational",
            source_id="status-page",
            source_text=source_text,
        )

        response = ExtractionResponse(
            facts=[
                ExtractedFact(
                    field_name="status",
                    value="operational",
                    source_id="status-page",
                    supporting_quote="Service status: operational.",
                    observation_time=observed_at.isoformat(),
                    confidence=0.99,
                )
            ],
            limitations=[],
            status="ok",
        )

        provider = FakeLLMProvider(response=response)
        policy = VerificationPolicy(
            policy_id="service-status",
            required_sources=["status-page"],
            claim_field="status",
            expected_value="operational",
            require_trusted_evidence=False,
        )

        result = await verify_with_llm(
            request.claim,
            request,
            policy,
            provider,
            checked_at=observed_at,
        )

        assert result.verdict == Verdict.VERIFIED

    asyncio.run(run())
