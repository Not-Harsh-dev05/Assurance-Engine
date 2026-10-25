
"""Provider-independent asynchronous LLM interface."""

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from assurance_engine.ai.schemas import (
    ExtractionRequest,
    ExtractionResponse,
)


@runtime_checkable
class LLMProvider(Protocol):
    """Contract that all extraction providers must implement."""

    async def extract(
        self,
        request: ExtractionRequest,
    ) -> ExtractionResponse:
        """Extract candidate facts from supplied source material."""
        ...


class FakeLLMProvider:
    """Deterministic provider for tests and local development."""

    def __init__(
        self,
        response: ExtractionResponse | None = None,
        *,
        error: Exception | None = None,
        handler: Callable[
            [ExtractionRequest],
            ExtractionResponse | Awaitable[ExtractionResponse],
        ]
        | None = None,
    ) -> None:
        if sum(
            item is not None
            for item in (response, error, handler)
        ) > 1:
            raise ValueError(
                "Specify at most one of response, error, or handler"
            )

        self._response = response
        self._error = error
        self._handler = handler
        self.requests: list[ExtractionRequest] = []

    async def extract(
        self,
        request: ExtractionRequest,
    ) -> ExtractionResponse:
        if not isinstance(request, ExtractionRequest):
            raise TypeError("request must be an ExtractionRequest")

        self.requests.append(request)

        if self._error is not None:
            raise self._error

        if self._handler is not None:
            result = self._handler(request)
            if isinstance(result, Awaitable):
                result = await result

            if not isinstance(result, ExtractionResponse):
                raise TypeError(
                    "Provider handler must return ExtractionResponse"
                )
            return result

        if self._response is not None:
            return self._response

        return ExtractionResponse(
            facts=[],
            status="insufficient_information",
            limitations=["Fake provider has no configured response."],
        )
