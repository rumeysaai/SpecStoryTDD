"""AlignmentEngine — core analysis module for SpecStoryTDD.

Responsibilities
----------------
1. Accept a User Story (Markdown) and an OpenAPI Spec (dict) as inputs.
2. Communicate with an LLM (via LangChain) to perform logical conflict analysis.
3. Synthesise auto-generated Pytest test suites from the analysis.
4. Implement a feedback-loop retry mechanism: if the LLM response does not
   conform to the expected JSON schema, the error is captured and the model
   is re-prompted with corrective context — up to ``max_retries`` times.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .models import AlignmentRequest, AlignmentResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert software architect specialising in API contract testing and \
behaviour-driven development. Your task is to analyse a User Story and an \
OpenAPI specification, identify logical conflicts between them, and produce a \
structured JSON report.

## Output format
Return **only** a valid JSON object that conforms to the following JSON Schema.
Do not include any markdown fences, prose, or extra keys.

```json
{
  "conflicts": [
    {
      "id": "C-001",
      "title": "...",
      "description": "...",
      "severity": "low|medium|high|critical",
      "story_reference": "...",
      "spec_reference": "...",
      "suggested_fix": "..."
    }
  ],
  "test_suite": [
    {
      "name": "test_...",
      "description": "...",
      "code": "def test_...(): ..."
    }
  ],
  "summary": "..."
}
```
"""


def _build_user_message(user_story: str, openapi_spec: dict[str, Any]) -> str:
    """Compose the user-facing prompt from the two input artefacts."""
    return (
        "## User Story\n\n"
        f"{user_story}\n\n"
        "## OpenAPI Specification\n\n"
        f"```json\n{json.dumps(openapi_spec, indent=2)}\n```\n\n"
        "Perform a thorough conflict analysis and return the JSON report."
    )


# ---------------------------------------------------------------------------
# AlignmentEngine
# ---------------------------------------------------------------------------


class AlignmentEngine:
    """Async engine that aligns User Stories with OpenAPI specs via an LLM.

    Parameters
    ----------
    llm_model:
        Name of the OpenAI chat model to use (default: ``"gpt-4o"``).
    temperature:
        Sampling temperature for the LLM (default: ``0.2``).
    """

    def __init__(
        self,
        llm_model: str = "gpt-4o",
        temperature: float = 0.2,
    ) -> None:
        self._llm = ChatOpenAI(model=llm_model, temperature=temperature)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyse(self, request: AlignmentRequest) -> AlignmentResult:
        """Run conflict analysis and test-suite generation.

        This method is the primary entry-point for consumers.  It wraps
        :meth:`_analyse_with_retry` so that callers always receive an
        :class:`AlignmentResult` or a clean exception.

        Parameters
        ----------
        request:
            Validated :class:`~backend.models.AlignmentRequest` containing the
            user story, OpenAPI spec, and retry configuration.

        Returns
        -------
        AlignmentResult
            Parsed and validated analysis result.

        Raises
        ------
        RuntimeError
            If the LLM fails to produce a valid response after all retries.
        """
        try:
            return await self._analyse_with_retry(
                user_story=request.user_story,
                openapi_spec=request.openapi_spec,
                max_retries=request.max_retries,
            )
        except RetryError as exc:
            raise RuntimeError(
                f"LLM failed to return a valid AlignmentResult after "
                f"{request.max_retries} attempts."
            ) from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _analyse_with_retry(
        self,
        user_story: str,
        openapi_spec: dict[str, Any],
        max_retries: int,
    ) -> AlignmentResult:
        """Invoke the LLM with a feedback-loop retry mechanism.

        On each attempt the method:
        1. Calls the LLM with the current prompt messages.
        2. Tries to parse and validate the JSON response against
           :class:`~backend.models.AlignmentResult`.
        3. If validation fails, appends the error detail to the conversation so
           the model can self-correct on the next attempt.

        The ``tenacity`` decorator handles transient network/rate-limit errors
        with exponential back-off; schema validation failures are handled
        manually inside the loop so the corrective feedback can be injected.
        """

        @retry(
            retry=retry_if_exception_type(Exception),
            stop=stop_after_attempt(max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            reraise=True,
        )
        async def _call_llm_with_backoff(
            messages: list[SystemMessage | HumanMessage],
        ) -> str:
            response = await self._llm.ainvoke(messages)
            return str(response.content)

        messages: list[SystemMessage | HumanMessage] = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_build_user_message(user_story, openapi_spec)),
        ]

        last_error: str = ""
        for attempt in range(1, max_retries + 1):
            if last_error:
                # Inject corrective feedback so the model can self-correct.
                messages.append(
                    HumanMessage(
                        content=(
                            f"Your previous response was invalid. Error details:\n\n"
                            f"{last_error}\n\n"
                            "Please return ONLY a valid JSON object that matches the "
                            "schema described in the system prompt. Do not include any "
                            "prose or markdown fences."
                        )
                    )
                )

            logger.info("AlignmentEngine: LLM attempt %d/%d", attempt, max_retries)

            raw_response: str = ""
            try:
                raw_response = await _call_llm_with_backoff(messages)
                result = self._parse_and_validate(raw_response)
                logger.info("AlignmentEngine: successfully parsed response on attempt %d", attempt)
                return result
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = str(exc)
                logger.warning(
                    "AlignmentEngine: attempt %d failed — %s",
                    attempt,
                    last_error,
                )
                # Append the assistant's bad reply to maintain conversation context.
                messages.append(HumanMessage(content=f"[Your invalid response]: {raw_response}"))

        raise RuntimeError(
            f"LLM did not produce a valid AlignmentResult after {max_retries} attempts. "
            f"Last error: {last_error}"
        )

    @staticmethod
    def _parse_and_validate(raw: str) -> AlignmentResult:
        """Parse a raw LLM string response into a validated :class:`AlignmentResult`.

        Parameters
        ----------
        raw:
            The raw string content returned by the LLM.

        Returns
        -------
        AlignmentResult
            Parsed and Pydantic-validated result.

        Raises
        ------
        json.JSONDecodeError
            If the response is not valid JSON.
        pydantic.ValidationError
            If the JSON does not match the :class:`AlignmentResult` schema.
        """
        # Strip common markdown code fences that models sometimes include.
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            # Remove opening fence (```json or ```) and closing fence (```)
            text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

        data = json.loads(text)
        return AlignmentResult.model_validate(data)
