
import pytest

from assurance_engine.ai.provider import (
    FakeLLMProvider,
    LLMProvider,
)
from assurance_engine.ai.schemas import (
    ExtractedFact,
    ExtractionRequest,
    ExtractionResponse,
)

@pytest.fixture
def extraction_request():
    return ExtractionRequest(
        claim="The service is operational",
        source_id="status-page",
        source_text="Service status: operational",
    )


@pytest.fixture
def response():
    return ExtractionResponse(
        facts=[
            ExtractedFact(
                field_name="status",
                value="operational",
                source_id="status-page",
                supporting_quote="Service status: operational",
                confidence=0.95,
            )
        ]
    )


@pytest.mark.asyncio
async def test_fake_provider_returns_configured_response(
    extraction_request, response
):
    provider = FakeLLMProvider(response=response)

    result = await provider.extract(extraction_request)

    assert result == response
    assert provider.requests == [extraction_request]


@pytest.mark.asyncio
async def test_fake_provider_without_response_is_inconclusive_input(
    extraction_request,
):
    provider = FakeLLMProvider()

    result = await provider.extract(extraction_request)

    assert result.facts == []
    assert result.status == "insufficient_information"


@pytest.mark.asyncio
async def test_fake_provider_propagates_provider_error(extraction_request):
    provider = FakeLLMProvider(
        error=RuntimeError("provider unavailable")
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await provider.extract(extraction_request)


@pytest.mark.asyncio
async def test_fake_provider_supports_handler(
    extraction_request, response
):
    provider = FakeLLMProvider(handler=lambda _: response)

    result = await provider.extract(extraction_request)

    assert result == response


@pytest.mark.asyncio
async def test_fake_provider_supports_async_handler(
    extraction_request, response
):
    async def handler(_):
        return response

    provider = FakeLLMProvider(handler=handler)

    result = await provider.extract(extraction_request)

    assert result == response


@pytest.mark.asyncio
async def test_fake_provider_rejects_invalid_handler_result(
    extraction_request,
):
    provider = FakeLLMProvider(handler=lambda _: {"facts": []})

    with pytest.raises(TypeError, match="ExtractionResponse"):
        await provider.extract(extraction_request)


def test_fake_provider_rejects_multiple_configurations(response):
    with pytest.raises(ValueError, match="at most one"):
        FakeLLMProvider(
            response=response,
            error=RuntimeError("failure"),
        )


def test_fake_provider_implements_provider_protocol():
    provider = FakeLLMProvider()

    assert isinstance(provider, LLMProvider)
