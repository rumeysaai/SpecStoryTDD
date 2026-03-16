"""FastAPI application for SpecStoryTDD.

Exposes a single ``POST /analyse`` endpoint that accepts an
:class:`~backend.models.AlignmentRequest` and returns an
:class:`~backend.models.AlignmentResult`.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, status

from .config import Settings, get_settings
from .engine import AlignmentEngine
from .models import AlignmentRequest, AlignmentResult

app = FastAPI(
    title="SpecStoryTDD API",
    description=(
        "Hybrid TDD/SDD framework that detects conflicts between User Stories "
        "and OpenAPI specifications, then auto-generates Pytest test suites."
    ),
    version="0.1.0",
)


def get_engine(settings: Settings = Depends(get_settings)) -> AlignmentEngine:
    """Dependency that provides a configured :class:`AlignmentEngine` instance."""
    return AlignmentEngine(
        llm_model=settings.llm_model,
        temperature=settings.llm_temperature,
    )


@app.get("/healthz", tags=["ops"])
async def healthcheck() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post(
    "/analyse",
    response_model=AlignmentResult,
    status_code=status.HTTP_200_OK,
    tags=["analysis"],
    summary="Analyse alignment between a User Story and an OpenAPI spec.",
)
async def analyse(
    request: AlignmentRequest,
    engine: AlignmentEngine = Depends(get_engine),
) -> AlignmentResult:
    """Run conflict analysis and test-suite generation.

    **Request body**
    - ``user_story``: User story in Markdown format.
    - ``openapi_spec``: OpenAPI 3.x specification as a JSON object.
    - ``max_retries`` *(optional)*: Maximum LLM retry attempts (default: 3).

    **Response**
    - ``conflicts``: List of detected logical conflicts.
    - ``test_suite``: Auto-generated Pytest test cases.
    - ``summary``: High-level narrative summary.
    """
    try:
        return await engine.analyse(request)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
