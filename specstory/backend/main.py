"""FastAPI entry point — ingestion ve /analyze."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .services.parser import parse_openapi_spec, parse_user_story

app = FastAPI(title="SpecStory", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeResponse(BaseModel):
    """LLM'e gönderilmeye hazır temizlenmiş context string'leri."""

    user_story_context: str = Field(..., description="User story'den türetilen context")
    technical_spec_context: str = Field(..., description="OpenAPI özet context")


class OpenAPISpecInput(BaseModel):
    """Yükleme sonrası JSON doğrulama — minimal OpenAPI şekli."""

    model_config = {"extra": "allow"}

    openapi: str | None = None
    swagger: str | None = None
    paths: dict[str, Any] = Field(default_factory=dict)

    @field_validator("paths")
    @classmethod
    def paths_must_be_dict(cls, v: Any) -> dict[str, Any]:
        if not isinstance(v, dict):
            raise ValueError("'paths' bir nesne (object) olmalıdır")
        return v

    @model_validator(mode="after")
    def openapi_or_swagger_present(self) -> OpenAPISpecInput:
        if not self.openapi and not self.swagger:
            raise ValueError(
                "OpenAPI belgesi 'openapi' veya 'swagger' alanı içermelidir"
            )
        return self


def _validate_openapi_dict(data: dict[str, Any]) -> None:
    try:
        OpenAPISpecInput.model_validate(data)
    except ValidationError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "OpenAPI JSON doğrulaması başarısız",
                "errors": e.errors(),
            },
        ) from e


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    user_story: Annotated[UploadFile, File(description="Markdown user story")],
    technical_spec: Annotated[UploadFile, File(description="OpenAPI JSON")],
) -> AnalyzeResponse:
    """
    User story (Markdown) ve teknik spec (OpenAPI JSON) yükler;
    parser ile LLM'e uygun context string'leri üretir.
    """
    if not user_story.filename:
        raise HTTPException(status_code=422, detail="user_story dosyası gerekli")
    if not technical_spec.filename:
        raise HTTPException(status_code=422, detail="technical_spec dosyası gerekli")

    raw_story = await user_story.read()
    try:
        story_text = raw_story.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(
            status_code=422,
            detail="user_story UTF-8 olarak okunamadı",
        ) from e

    raw_spec = await technical_spec.read()
    try:
        spec_text = raw_spec.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(
            status_code=422,
            detail="technical_spec UTF-8 olarak okunamadı",
        ) from e

    try:
        spec_dict = json.loads(spec_text)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=422,
            detail={"message": "technical_spec geçerli JSON değil", "errors": str(e)},
        ) from e

    if not isinstance(spec_dict, dict):
        raise HTTPException(
            status_code=422,
            detail="OpenAPI kökü bir JSON nesnesi olmalıdır",
        )

    _validate_openapi_dict(spec_dict)

    user_story_context = parse_user_story(story_text)
    technical_spec_context = parse_openapi_spec(spec_dict)

    return AnalyzeResponse(
        user_story_context=user_story_context,
        technical_spec_context=technical_spec_context,
    )
