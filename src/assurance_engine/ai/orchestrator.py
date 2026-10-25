
"""Orchestrate LLM extraction without delegating verdict authority."""

import asyncio
import math
from datetime import datetime

from assurance_engine.ai.grounding import fact_to_evidence
from assurance_engine.ai.provider import LLMProvider
from assurance_engine.ai.schemas import (
    ExtractionRequest,
    ExtractionResponse,
)
from assurance_engine.engine import verify
from assurance_engine.schemas import (
    Evidence,
    Finding,
    VerificationPolicy,
    VerificationResult,
)


def _add_finding(
    result: VerificationResult,
    *,
    code: str,
    message: str,
) -> VerificationResult:
    """Add an AI-pipeline diagnostic without changing the engine verdict."""
    return VerificationResult(
        claim=result.claim,
        verdict=result.verdict,
        findings=[
            *result.findings,
            Finding(code=code, message=message),
        ],
        checked_at=result.checked_at,
    )


async def verify_with_llm(
    claim: str,
    request: ExtractionRequest,
    policy: VerificationPolicy,
    provider: LLMProvider,
    *,
    checked_at: datetime | None = None,
    timeout_seconds: float = 10.0,
) -> VerificationResult:
    """Extract candidate evidence and delegate the verdict to verify().

    Provider failures and grounding failures result in verification with
    no evidence. Extracted evidence is never promoted to trusted status.
    """
    if not isinstance(request, ExtractionRequest):
        raise TypeError("request must be an ExtractionRequest")

    if not isinstance(provider, LLMProvider):
        raise TypeError("provider must implement LLMProvider")

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError(
            "timeout_seconds must be a finite number greater than zero"
        )

    # Validate core inputs before entering the AI error-handling path.
    if not isinstance(policy, VerificationPolicy):
        raise TypeError("policy must be a VerificationPolicy")

    if not isinstance(claim, str) or not claim.strip():
        raise ValueError("claim must be a non-empty string")

    if request.claim != claim:
        base_result = verify(
            claim,
            [],
            policy,
            checked_at=checked_at,
        )
        return _add_finding(
            base_result,
            code="AI_REQUEST_CLAIM_MISMATCH",
            message=(
                "The extraction request claim does not match "
                "the claim being verified."
            ),
        )

    try:
        async with asyncio.timeout(timeout_seconds):
            response = await provider.extract(request)
    except Exception:
        base_result = verify(
            claim,
            [],
            policy,
            checked_at=checked_at,
        )
        return _add_finding(
            base_result,
            code="AI_EXTRACTION_FAILED",
            message=(
                "AI extraction failed or timed out; "
                "no extracted evidence was used."
            ),
        )

    if not isinstance(response, ExtractionResponse):
        base_result = verify(
            claim,
            [],
            policy,
            checked_at=checked_at,
        )
        return _add_finding(
            base_result,
            code="AI_INVALID_RESPONSE",
            message="The provider returned an invalid extraction response.",
        )

    if response.status != "ok" or not response.facts:
        base_result = verify(
            claim,
            [],
            policy,
            checked_at=checked_at,
        )
        return _add_finding(
            base_result,
            code="AI_INSUFFICIENT_INFORMATION",
            message="The extraction returned no usable facts.",
        )

    candidate_evidence: list[Evidence] = []

    try:
        for index, fact in enumerate(response.facts):
            if (
                policy.claim_field is not None
                and fact.field_name != policy.claim_field
            ):
                raise ValueError(
                    "Extracted fact does not match the policy claim field."
                )

            evidence = fact_to_evidence(fact, request)
            evidence = evidence.model_copy(
                update={
                    "evidence_id": f"{evidence.evidence_id}:{index}"
                }
            )
            candidate_evidence.append(evidence)

    except Exception:
        base_result = verify(
            claim,
            [],
            policy,
            checked_at=checked_at,
        )
        return _add_finding(
            base_result,
            code="AI_GROUNDING_FAILED",
            message=(
                "One or more extracted facts failed grounding or "
                "policy field validation; no extracted evidence was used."
            ),
        )

    # Only the deterministic engine determines the final verdict.
    return verify(
        claim,
        candidate_evidence,
        policy,
        checked_at=checked_at,
    )
