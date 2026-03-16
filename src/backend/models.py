"""Pydantic models for SpecStoryTDD inputs and outputs."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class AlignmentRequest(BaseModel):
    """Payload sent to the AlignmentEngine for analysis."""

    user_story: str = Field(
        ...,
        description="User story in Markdown format.",
        examples=["## As a user I want to login so that I can access my account."],
    )
    openapi_spec: dict[str, Any] = Field(
        ...,
        description="OpenAPI 3.x specification as a parsed JSON/dict object.",
    )
    max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum number of LLM retry attempts on schema validation failure.",
    )


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class SeverityLevel(str, Enum):
    """Conflict severity classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Conflict(BaseModel):
    """A single logical conflict detected between a user story and an OpenAPI spec."""

    id: str = Field(..., description="Unique conflict identifier, e.g. 'C-001'.")
    title: str = Field(..., description="Short human-readable title of the conflict.")
    description: str = Field(..., description="Detailed description of the conflict.")
    severity: SeverityLevel = Field(..., description="Severity level of the conflict.")
    story_reference: str = Field(
        ..., description="Quoted passage from the user story that triggers the conflict."
    )
    spec_reference: str = Field(
        ...,
        description="JSON path or operation ID in the OpenAPI spec related to the conflict.",
    )
    suggested_fix: str = Field(
        ..., description="Actionable recommendation to resolve the conflict."
    )


class TestCase(BaseModel):
    """An auto-generated Pytest test case."""

    name: str = Field(..., description="Python-valid test function name, e.g. 'test_login_401'.")
    description: str = Field(..., description="Human-readable description of what is being tested.")
    code: str = Field(..., description="Complete Pytest function source code as a string.")


class AlignmentResult(BaseModel):
    """Full analysis result returned by the AlignmentEngine."""

    conflicts: list[Conflict] = Field(default_factory=list)
    test_suite: list[TestCase] = Field(default_factory=list)
    summary: str = Field(
        default="",
        description="High-level narrative summary of the alignment analysis.",
    )
