"""Anthropic ve OpenAI ile dual-model asenkron orchestration."""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from openai import AsyncOpenAI

_BACKEND_DOTENV = Path(__file__).resolve().parent.parent / ".env"
if _BACKEND_DOTENV.is_file():
    load_dotenv(_BACKEND_DOTENV)

SEMANTIC_ALIGNER_SYSTEM = """You are a Semantic Aligner.
You receive (1) User Story context and (2) OpenAPI-derived technical context.
Your job:
- Find logical gaps: requirements or behaviours implied by the story that the API contract does not cover or under-specifies.
- Find contradictions: places where the story and the spec cannot both be true, or where response/request expectations conflict.

Output rules:
- Respond with ONLY a single JSON object (no markdown fences, no commentary).
- Use exactly this shape:
{"logical_gaps":[{"id":"string","description":"string"}],"contradictions":[{"id":"string","story_ref":"string","spec_ref":"string","description":"string"}]}
- Use empty arrays if none found.
"""


def _test_architect_system_claude() -> str:
    return """You are a Test Architect working alongside another LLM (e.g. GPT).
Given User Story context and OpenAPI-derived technical context:
- Generate executable Python pytest code that encodes relevant technical constraints (minimum, maximum, enum, required fields, status codes, etc.) and ties tests to acceptance criteria where possible.
- Propose boundary-value edge cases that GPT-style models often miss (off-by-one, exclusive bounds, empty collections, duplicate enum edge paths, nullable vs omitted, etc.).

Output rules:
- Respond with ONLY a single JSON object (no markdown fences, no commentary).
- Use exactly this shape:
{"pytest_code":"string","boundary_value_edge_cases":[{"case":"string","rationale":"string"}]}
- pytest_code must be a single string with newlines escaped as \\n in JSON (standard JSON string).
"""


def _test_architect_system_gpt() -> str:
    return """You are a Test Architect working alongside another LLM (e.g. Claude).
Given User Story context and OpenAPI-derived technical context:
- Generate executable Python pytest code that encodes relevant technical constraints (minimum, maximum, enum, required fields, status codes, etc.) and ties tests to acceptance criteria where possible.
- Propose boundary-value edge cases that Claude-style models often miss (subtle state coupling, implicit ordering assumptions, rare enum combinations, implicit defaults in OpenAPI, etc.).

Output rules:
- Respond with ONLY a single JSON object (no markdown fences, no commentary).
- Use exactly this shape:
{"pytest_code":"string","boundary_value_edge_cases":[{"case":"string","rationale":"string"}]}
- pytest_code must be a valid JSON string (escape newlines per JSON rules).
"""


def _build_user_message(story_ctx: str, spec_ctx: str) -> str:
    return (
        "### User Story Context\n\n"
        f"{story_ctx.strip()}\n\n"
        "### Technical Spec Context\n\n"
        f"{spec_ctx.strip()}"
    )


REVIEWER_GPT_SYSTEM = """Sen deneyimli bir API / ürün spesifikasyonu inceleyicisisin (Reviewer).
Başka bir model (Claude) kullanıcı mesajında verilen JSON çelişki kaydını tespit etti.
Teknik spesifikasyon (OpenAPI özeti) ve User Story bağlamına dayanarak karar ver:
Bu gerçek bir tutarsızlık mı (hata), yoksa yanlış alarm mı (yanlis_alarm)?

Yanıtın YALNIZCA tek bir geçerli JSON nesnesi olsun (markdown, kod çiti yok).
Şema:
{"verdict": "hata" | "yanlis_alarm", "rationale": "string"}
- verdict "hata": Story ile spec gerçekten çelişiyor veya story gereksinimi spec ile doğrulanmıyor.
- verdict "yanlis_alarm": Claude yanlış okumuş, spekülatif veya sözleşmede dayanağı yok.
"""


REVIEWER_CLAUDE_SYSTEM = """You are an expert API and product-spec reviewer.
Another model (GPT) reported a possible contradiction between the User Story and the OpenAPI-derived technical context (JSON record in the user message).
Decide: real inconsistency ("hata") or false alarm ("yanlis_alarm").

Reply with ONLY one valid JSON object (no markdown).
Schema: {"verdict": "hata" | "yanlis_alarm", "rationale": "string"}
Semantics: hata = true conflict or unmet story requirement vs spec; yanlis_alarm = misread or unsupported claim.
"""


def _build_peer_review_user_message(
    peer_model_label: str,
    contradiction: dict[str, Any],
    story_ctx: str,
    spec_ctx: str,
) -> str:
    payload = json.dumps(contradiction, ensure_ascii=False, indent=2)
    return (
        f"{peer_model_label} şu çelişkiyi tespit etti. Teknik spesifikasyonlara göre "
        "bu bir hata mı yoksa yanlış alarm mı? Cevabını nedenleriyle belirt; "
        "son kararını sistem mesajındaki JSON şemasına uygun ver.\n\n"
        f"### {peer_model_label} çelişki kaydı (JSON)\n{payload}\n\n"
        "### User Story Context\n\n"
        f"{story_ctx.strip()}\n\n"
        "### Technical Spec Context\n\n"
        f"{spec_ctx.strip()}"
    )


DEFAULT_GENERATED_TESTS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "tests" / "generated"
)


GENERATE_EXECUTABLE_TESTS_SYSTEM = """You are a senior Python test engineer.
Produce EXACTLY one pytest module as plain Python source (a single file).

Mandatory content:
- Use pytest. Include at least one @pytest.mark.parametrize covering boundary / edge values derived from the provided approved edge cases JSON.
- Use httpx (sync Client is fine) to exercise HTTP APIs. Base URL MUST be read from environment variable SPECSTORY_TEST_BASE_URL with default "http://127.0.0.1:8000".
- Add explicit tests for failure scenarios implied by the spec (e.g. insufficient balance, validation errors, 4xx responses): use clear assert blocks on status_code and/or JSON body fields.
- CI/CD (GitHub Actions) friendly: no input(), no GUI, no secrets in code; mark slow tests with @pytest.mark.integration if they need a running server; skip gracefully when SPECSTORY_SKIP_LIVE=1 if you add such checks (optional but preferred).

Output rules — CRITICAL:
- Output ONLY executable Python code. No markdown fences, no commentary before or after the code.
- Sadece kod dön, açıklama yapma ve kodun CI/CD pipeline'ında (GitHub Actions) çalışabilir olduğundan emin ol.
"""


def _sanitize_analysis_slug(slug: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "_", (slug or "analysis").strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "analysis"


def _strip_python_code_fence(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:python|py)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def _next_generated_test_path(output_dir: Path, slug: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    for n in range(1, 1000):
        candidate = output_dir / f"test_{slug}_v{n}.py"
        if not candidate.exists():
            return candidate
    return output_dir / f"test_{slug}_{uuid.uuid4().hex[:10]}.py"


def _build_codegen_user_payload(
    approved_edge_cases: list[dict[str, Any]],
    spec_ctx: str,
    story_ctx: str,
) -> str:
    cases = json.dumps(approved_edge_cases, ensure_ascii=False, indent=2)
    parts = [
        "### Approved Edge Cases (JSON)\n",
        cases,
        "\n\n### Technical Spec / OpenAPI Context\n\n",
        spec_ctx.strip(),
    ]
    if story_ctx.strip():
        parts.extend(["\n\n### User Story Context\n\n", story_ctx.strip()])
    return "".join(parts)


def _strip_json_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def _safe_parse_json_object(raw: str) -> dict[str, Any]:
    cleaned = _strip_json_fence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return {"_parse_error": True, "_raw": raw}
    if isinstance(data, dict):
        return data
    return {"_parse_error": True, "_raw": raw, "_parsed": data}


class MultiModelEngine:
    """
    Paralel Semantic Aligner + Test Architect çağrıları ile Claude Opus ve GPT modellerini orkestre eder.
    """

    def __init__(
        self,
        *,
        anthropic_api_key: str | None = None,
        openai_api_key: str | None = None,
        anthropic_model: str | None = None,
        openai_model: str | None = None,
    ) -> None:
        a_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        o_key = (
            openai_api_key
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("OPENAI_KEY")
        )
        if not a_key:
            raise ValueError("ANTHROPIC_API_KEY ortam değişkeni veya anthropic_api_key gerekli")
        if not o_key:
            raise ValueError(
                "OPENAI_API_KEY (veya OPENAI_KEY) .env / ortamda tanımlı olmalı veya openai_api_key gerekli"
            )

        self._anthropic = AsyncAnthropic(api_key=a_key)
        self._openai = AsyncOpenAI(api_key=o_key)
        self._anthropic_model = anthropic_model or os.environ.get(
            "SPECSTORY_ANTHROPIC_MODEL",
            "claude-opus-4-5-20251101",
        )
        self._openai_model = openai_model or os.environ.get(
            "SPECSTORY_OPENAI_MODEL",
            "gpt-5.2",
        )

    async def _claude_text(self, *, system: str, user: str) -> str:
        msg = await self._anthropic.messages.create(
            model=self._anthropic_model,
            max_tokens=20000,
            temperature=1,
            system=system,
            messages=[{"role": "user", "content": user}],
            thinking={"type": "enabled",
        "budget_tokens": 16000},
            output_config={"effort": "high"},
        )
        parts: list[str] = []
        for block in msg.content:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", ""))
        return "".join(parts).strip()

    async def _openai_responses_text(self, *, system: str, user: str) -> str:
        """GPT-5.x Responses API — OPENAI_API_KEY .env üzerinden yüklenir."""
        resp = await self._openai.responses.create(
            model=self._openai_model,
            instructions=system,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": user,
                        }
                    ],
                }
            ],
            text={
                "format": {"type": "text"},
                "verbosity": "medium",
            },
            reasoning={
                "effort": "medium",
                "summary": "auto",
            },
            tools=[],
            store=True,
            include=[
                "reasoning.encrypted_content",
                "web_search_call.action.sources",
            ],
        )
        return (getattr(resp, "output_text", None) or "").strip()

    async def generate_python_source(self, *, system: str, user: str) -> str:
        """Claude ile ham metin üretir; markdown kod çitleri varsa temizler."""
        raw = await self._claude_text(system=system, user=user)
        return _strip_python_code_fence(raw)

    async def _claude_aligner(self, story_ctx: str, spec_ctx: str) -> dict[str, Any]:
        user = _build_user_message(story_ctx, spec_ctx)
        raw = await self._claude_text(system=SEMANTIC_ALIGNER_SYSTEM, user=user)
        return _safe_parse_json_object(raw)

    async def _claude_architect(self, story_ctx: str, spec_ctx: str) -> dict[str, Any]:
        user = _build_user_message(story_ctx, spec_ctx)
        raw = await self._claude_text(
            system=_test_architect_system_claude(),
            user=user,
        )
        return _safe_parse_json_object(raw)

    async def _gpt_aligner(self, story_ctx: str, spec_ctx: str) -> dict[str, Any]:
        user = _build_user_message(story_ctx, spec_ctx)
        raw = await self._openai_responses_text(system=SEMANTIC_ALIGNER_SYSTEM, user=user)
        return _safe_parse_json_object(raw)

    async def _gpt_architect(self, story_ctx: str, spec_ctx: str) -> dict[str, Any]:
        user = _build_user_message(story_ctx, spec_ctx)
        raw = await self._openai_responses_text(
            system=_test_architect_system_gpt(),
            user=user,
        )
        return _safe_parse_json_object(raw)

    async def call_claude_opus(self, story_ctx: str, spec_ctx: str) -> dict[str, Any]:
        """Claude Opus: Semantic Aligner ve Test Architect paralel; sonuçlar tek sözlükte."""
        semantic, architect = await asyncio.gather(
            self._claude_aligner(story_ctx, spec_ctx),
            self._claude_architect(story_ctx, spec_ctx),
        )
        return {
            "model": self._anthropic_model,
            "semantic_alignment": semantic,
            "test_architecture": architect,
        }

    async def call_gpt_five(self, story_ctx: str, spec_ctx: str) -> dict[str, Any]:
        """GPT: Semantic Aligner ve Test Architect paralel; sonuçlar tek sözlükte."""
        semantic, architect = await asyncio.gather(
            self._gpt_aligner(story_ctx, spec_ctx),
            self._gpt_architect(story_ctx, spec_ctx),
        )
        return {
            "model": self._openai_model,
            "semantic_alignment": semantic,
            "test_architecture": architect,
        }

    async def run_dual(self, story_ctx: str, spec_ctx: str) -> dict[str, Any]:
        """Claude ve GPT çağrılarını paralel yürütür; çıktıları birleştirir."""
        claude_out, gpt_out = await asyncio.gather(
            self.call_claude_opus(story_ctx, spec_ctx),
            self.call_gpt_five(story_ctx, spec_ctx),
        )
        return {
            "claude": claude_out,
            "openai": gpt_out,
        }

    async def gpt_peer_review_contradiction(
        self,
        *,
        story_ctx: str,
        spec_ctx: str,
        contradiction: dict[str, Any],
    ) -> dict[str, Any]:
        """Claude'un bir çelişkisini GPT-5.x (Responses API) ile Reviewer olarak değerlendirir."""
        user = _build_peer_review_user_message("Claude", contradiction, story_ctx, spec_ctx)
        raw = await self._openai_responses_text(
            system=REVIEWER_GPT_SYSTEM,
            user=user,
        )
        return _safe_parse_json_object(raw)

    async def claude_peer_review_contradiction(
        self,
        *,
        story_ctx: str,
        spec_ctx: str,
        contradiction: dict[str, Any],
    ) -> dict[str, Any]:
        """GPT'nin bir çelişkisini Claude ile Reviewer olarak değerlendirir (çapraz doğrulama)."""
        user = _build_peer_review_user_message("GPT", contradiction, story_ctx, spec_ctx)
        raw = await self._claude_text(
            system=REVIEWER_CLAUDE_SYSTEM,
            user=user,
        )
        return _safe_parse_json_object(raw)


async def generate_executable_tests(
    *,
    approved_edge_cases: list[dict[str, Any]],
    spec_ctx: str,
    story_ctx: str = "",
    analysis_slug: str = "specstory_analysis",
    output_dir: Path | str | None = None,
    engine: MultiModelEngine | None = None,
) -> dict[str, Any]:
    """
    Onaylanmış edge case'ler ve spec özetinden Pytest dosyası üretir;
    ``specstory/tests/generated/`` altına ``test_{slug}_v{n}.py`` benzersiz adla yazar.

    Üretim Claude (MultiModelEngine) ile yapılır; çıktıda yalnızca çalıştırılabilir kod olması istenir.
    """
    eng = engine or MultiModelEngine()
    slug = _sanitize_analysis_slug(analysis_slug)
    out = Path(output_dir) if output_dir else DEFAULT_GENERATED_TESTS_DIR
    target = _next_generated_test_path(out, slug)

    user = _build_codegen_user_payload(approved_edge_cases, spec_ctx, story_ctx)
    body = await eng.generate_python_source(
        system=GENERATE_EXECUTABLE_TESTS_SYSTEM,
        user=user,
    )
    if not body:
        raise ValueError("Model boş veya geçersiz test kodu döndürdü")

    header = (
        f"# Generated by SpecStory — {analysis_slug}\n"
        "# SPECSTORY_TEST_BASE_URL env overrides API host (default http://127.0.0.1:8000)\n\n"
    )
    final_source = header + body
    if not final_source.endswith("\n"):
        final_source += "\n"

    target.write_text(final_source, encoding="utf-8")
    return {
        "path": str(target.resolve()),
        "relative_path": str(target),
        "bytes": len(final_source.encode("utf-8")),
    }
