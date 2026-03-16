"""Unit tests for AlignmentEngine and supporting modules.

These tests do NOT require a live LLM; the LLM call is patched so the
test suite can run offline (e.g. in CI without an OpenAI key).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.engine import AlignmentEngine
from src.backend.models import (
    AlignmentRequest,
    AlignmentResult,
    Conflict,
    SeverityLevel,
    TestCase,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_USER_STORY = """\
## As a registered user
I want to **log in** with my email and password
So that I can access my personalised dashboard.

### Acceptance Criteria
- Given valid credentials, the API returns HTTP 200 with a JWT token.
- Given invalid credentials, the API returns HTTP 401.
- The login endpoint must NOT expose the password in any response.
"""

SAMPLE_OPENAPI_SPEC: dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Auth API", "version": "1.0.0"},
    "paths": {
        "/login": {
            "post": {
                "operationId": "login",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "email": {"type": "string"},
                                    "password": {"type": "string"},
                                },
                                "required": ["email", "password"],
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Successful login",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "token": {"type": "string"},
                                        "password": {"type": "string"},  # intentional conflict
                                    },
                                }
                            }
                        },
                    },
                    "400": {"description": "Bad Request"},  # missing 401 — intentional conflict
                },
            }
        }
    },
}

VALID_LLM_RESPONSE = json.dumps(
    {
        "conflicts": [
            {
                "id": "C-001",
                "title": "Missing 401 response",
                "description": "The user story requires a 401 for invalid credentials but the spec only defines 400.",
                "severity": "high",
                "story_reference": "the API returns HTTP 401",
                "spec_reference": "/login > post > responses",
                "suggested_fix": "Add a 401 response definition to the /login POST operation.",
            },
            {
                "id": "C-002",
                "title": "Password exposed in response",
                "description": "The spec includes 'password' in the 200 response schema, violating the acceptance criterion.",
                "severity": "critical",
                "story_reference": "must NOT expose the password in any response",
                "spec_reference": "/login > post > responses > 200 > content > application/json > schema > properties > password",
                "suggested_fix": "Remove the 'password' property from the 200 response schema.",
            },
        ],
        "test_suite": [
            {
                "name": "test_login_returns_401_for_invalid_credentials",
                "description": "Ensure the login endpoint returns 401 when credentials are invalid.",
                "code": (
                    "def test_login_returns_401_for_invalid_credentials(client):\n"
                    "    response = client.post('/login', json={'email': 'bad@example.com', 'password': 'wrong'})\n"
                    "    assert response.status_code == 401\n"
                ),
            }
        ],
        "summary": "Found 2 conflicts: a missing 401 response and an exposed password field.",
    }
)


@pytest.fixture
def alignment_request() -> AlignmentRequest:
    return AlignmentRequest(
        user_story=SAMPLE_USER_STORY,
        openapi_spec=SAMPLE_OPENAPI_SPEC,
        max_retries=3,
    )


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestAlignmentRequest:
    def test_valid_request(self, alignment_request: AlignmentRequest) -> None:
        assert alignment_request.user_story == SAMPLE_USER_STORY
        assert alignment_request.openapi_spec == SAMPLE_OPENAPI_SPEC
        assert alignment_request.max_retries == 3

    def test_max_retries_bounds(self) -> None:
        with pytest.raises(Exception):
            AlignmentRequest(
                user_story="story",
                openapi_spec={},
                max_retries=0,  # below minimum of 1
            )

    def test_default_max_retries(self) -> None:
        req = AlignmentRequest(user_story="story", openapi_spec={})
        assert req.max_retries == 3


class TestAlignmentResult:
    def test_parse_valid_result(self) -> None:
        result = AlignmentResult.model_validate(json.loads(VALID_LLM_RESPONSE))
        assert len(result.conflicts) == 2
        assert result.conflicts[0].severity == SeverityLevel.HIGH
        assert result.conflicts[1].severity == SeverityLevel.CRITICAL
        assert len(result.test_suite) == 1
        assert "401" in result.test_suite[0].name

    def test_empty_result(self) -> None:
        result = AlignmentResult()
        assert result.conflicts == []
        assert result.test_suite == []
        assert result.summary == ""

    def test_conflict_fields(self) -> None:
        conflict = Conflict(
            id="C-001",
            title="Test",
            description="Desc",
            severity=SeverityLevel.MEDIUM,
            story_reference="ref",
            spec_reference="/path",
            suggested_fix="Fix it",
        )
        assert conflict.id == "C-001"
        assert conflict.severity == SeverityLevel.MEDIUM

    def test_test_case_fields(self) -> None:
        tc = TestCase(
            name="test_something",
            description="Tests something",
            code="def test_something(): assert True",
        )
        assert tc.name == "test_something"


# ---------------------------------------------------------------------------
# AlignmentEngine._parse_and_validate tests
# ---------------------------------------------------------------------------


class TestParseAndValidate:
    def test_parses_valid_json(self) -> None:
        result = AlignmentEngine._parse_and_validate(VALID_LLM_RESPONSE)
        assert isinstance(result, AlignmentResult)
        assert len(result.conflicts) == 2

    def test_strips_markdown_fences(self) -> None:
        fenced = f"```json\n{VALID_LLM_RESPONSE}\n```"
        result = AlignmentEngine._parse_and_validate(fenced)
        assert isinstance(result, AlignmentResult)

    def test_strips_plain_fences(self) -> None:
        fenced = f"```\n{VALID_LLM_RESPONSE}\n```"
        result = AlignmentEngine._parse_and_validate(fenced)
        assert isinstance(result, AlignmentResult)

    def test_raises_on_invalid_json(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            AlignmentEngine._parse_and_validate("not json at all")

    def test_raises_on_schema_mismatch(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AlignmentEngine._parse_and_validate('{"conflicts": "wrong_type"}')


# ---------------------------------------------------------------------------
# AlignmentEngine.analyse integration (LLM mocked)
# ---------------------------------------------------------------------------


class TestAlignmentEngineAnalyse:
    @pytest.fixture
    def engine(self) -> AlignmentEngine:
        # Provide a dummy API key so ChatOpenAI can be instantiated without
        # a real credential — the actual LLM call is always mocked below.
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-dummy"}):
            return AlignmentEngine()

    @pytest.mark.asyncio
    async def test_analyse_success_on_first_attempt(
        self, engine: AlignmentEngine, alignment_request: AlignmentRequest
    ) -> None:
        mock_response = MagicMock()
        mock_response.content = VALID_LLM_RESPONSE

        with patch("langchain_openai.ChatOpenAI.ainvoke", new=AsyncMock(return_value=mock_response)):
            result = await engine.analyse(alignment_request)

        assert isinstance(result, AlignmentResult)
        assert len(result.conflicts) == 2
        assert result.conflicts[0].id == "C-001"

    @pytest.mark.asyncio
    async def test_analyse_retries_on_bad_json_then_succeeds(
        self, engine: AlignmentEngine, alignment_request: AlignmentRequest
    ) -> None:
        bad_response = MagicMock()
        bad_response.content = "this is not json"
        good_response = MagicMock()
        good_response.content = VALID_LLM_RESPONSE

        with patch(
            "langchain_openai.ChatOpenAI.ainvoke",
            new=AsyncMock(side_effect=[bad_response, good_response]),
        ):
            result = await engine.analyse(alignment_request)

        assert isinstance(result, AlignmentResult)

    @pytest.mark.asyncio
    async def test_analyse_raises_after_all_retries_exhausted(
        self, engine: AlignmentEngine
    ) -> None:
        request = AlignmentRequest(
            user_story="story", openapi_spec={}, max_retries=2
        )
        bad_response = MagicMock()
        bad_response.content = "bad json"

        with patch(
            "langchain_openai.ChatOpenAI.ainvoke",
            new=AsyncMock(return_value=bad_response),
        ):
            with pytest.raises(RuntimeError, match="valid AlignmentResult"):
                await engine.analyse(request)
