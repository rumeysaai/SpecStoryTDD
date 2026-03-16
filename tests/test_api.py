"""Integration tests for the FastAPI application.

The LLM layer is mocked so these tests run fully offline.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.backend.api import app, get_engine
from src.backend.engine import AlignmentEngine
from src.backend.models import AlignmentResult


VALID_RESULT = AlignmentResult.model_validate(
    {
        "conflicts": [],
        "test_suite": [],
        "summary": "No conflicts found.",
    }
)

SAMPLE_PAYLOAD = {
    "user_story": "## As a user I want to log in so I can access my dashboard.",
    "openapi_spec": {
        "openapi": "3.1.0",
        "info": {"title": "Test", "version": "1.0.0"},
        "paths": {},
    },
}


@pytest.fixture
def mock_engine() -> AlignmentEngine:
    engine = MagicMock(spec=AlignmentEngine)
    engine.analyse = AsyncMock(return_value=VALID_RESULT)
    return engine


@pytest.fixture
def client(mock_engine: AlignmentEngine) -> AsyncClient:
    app.dependency_overrides[get_engine] = lambda: mock_engine
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_healthcheck(client: AsyncClient) -> None:
    async with client as c:
        response = await c.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_analyse_returns_200(client: AsyncClient) -> None:
    async with client as c:
        response = await c.post("/analyse", json=SAMPLE_PAYLOAD)
    assert response.status_code == 200
    data = response.json()
    assert "conflicts" in data
    assert "test_suite" in data
    assert "summary" in data


@pytest.mark.asyncio
async def test_analyse_returns_502_on_runtime_error(
    mock_engine: AlignmentEngine,
) -> None:
    mock_engine.analyse = AsyncMock(side_effect=RuntimeError("LLM failed"))
    app.dependency_overrides[get_engine] = lambda: mock_engine
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.post("/analyse", json=SAMPLE_PAYLOAD)
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_analyse_validates_request_body() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Missing required fields
        response = await c.post("/analyse", json={})
    assert response.status_code == 422
