
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from assurance_engine.ai.openai_provider import OpenAIProvider
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
def valid_response():
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


def make_client(parsed_response):
    parse = AsyncMock(
        return_value=SimpleNamespace(output_parsed=parsed_response)
    )
    close = AsyncMock()

    client = SimpleNamespace(
        responses=SimpleNamespace(parse=parse),
        close=close,
    )
    return client, parse, close


@pytest.mark.asyncio
async def test_extract_returns_validated_structured_response(
    extraction_request, valid_response
):
    client, parse, _ = make_client(valid_response)
    provider = OpenAIProvider(model="test-model", client=client)

    result = await provider.extract(extraction_request)

    assert result == valid_response
    parse.assert_awaited_once()

    call_kwargs = parse.await_args.kwargs
    assert call_kwargs["model"] == "test-model"
    assert call_kwargs["text_format"] is ExtractionResponse

    submitted_input = call_kwargs["input"]
    assert extraction_request.source_text in submitted_input[1]["content"]
    assert extraction_request.claim in submitted_input[1]["content"]


@pytest.mark.asyncio
async def test_missing_parsed_output_fails_closed(extraction_request):
    client, _, _ = make_client(None)
    provider = OpenAIProvider(client=client)

    result = await provider.extract(extraction_request)

    assert result.status == "insufficient_information"
    assert result.facts == []
    assert result.limitations


@pytest.mark.asyncio
async def test_invalid_request_type_is_rejected():
    client, parse, _ = make_client(None)
    provider = OpenAIProvider(client=client)

    with pytest.raises(TypeError, match="ExtractionRequest"):
        await provider.extract("not a request")

    parse.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_closes_underlying_client():
    client, _, close = make_client(None)
    provider = OpenAIProvider(client=client)

    await provider.close()

    close.assert_awaited_once()


def test_blank_model_is_rejected():
    with pytest.raises(ValueError, match="model"):
        OpenAIProvider(model="   ", client=object())


def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="API key is missing"):
        OpenAIProvider()


def test_api_key_can_be_read_from_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")

    provider = OpenAIProvider()

    try:
        assert provider._client.api_key == "test-key-not-real"
    finally:
        import asyncio
        asyncio.run(provider.close())


def test_model_is_trimmed():
    client, _, _ = make_client(None)
    provider = OpenAIProvider(model="  test-model  ", client=client)

    assert provider._model == "test-model"
