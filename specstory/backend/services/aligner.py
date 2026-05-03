"""Semantic alignment ve model-ara peer-review döngüsü."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Literal

from specstory.backend.services.llm_service import MultiModelEngine


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return []


def _extract_contradictions(semantic_alignment: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not semantic_alignment or not isinstance(semantic_alignment, dict):
        return []
    raw = semantic_alignment.get("contradictions")
    out: list[dict[str, Any]] = []
    for item in _as_list(raw):
        if isinstance(item, dict):
            out.append(item)
    return out


def _extract_edge_cases(test_architecture: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not test_architecture or not isinstance(test_architecture, dict):
        return []
    raw = test_architecture.get("boundary_value_edge_cases")
    out: list[dict[str, Any]] = []
    for item in _as_list(raw):
        if isinstance(item, dict):
            out.append(item)
    return out


def _extract_logical_gaps(semantic_alignment: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not semantic_alignment or not isinstance(semantic_alignment, dict):
        return []
    out: list[dict[str, Any]] = []
    for item in _as_list(semantic_alignment.get("logical_gaps")):
        if isinstance(item, dict):
            out.append(item)
    return out


Verdict = Literal["hata", "yanlis_alarm", "unknown"]


def _normalize_verdict(parsed: dict[str, Any]) -> Verdict:
    if parsed.get("_parse_error"):
        return "unknown"
    v = parsed.get("verdict")
    if not isinstance(v, str):
        return "unknown"
    vl = v.strip().lower().replace(" ", "_").replace("ı", "i")
    if vl in ("hata", "error", "true_positive", "inconsistency"):
        return "hata"
    if vl in (
        "yanlis_alarm",
        "yanlış_alarm",
        "false_alarm",
        "falsepositive",
        "false_positive",
    ):
        return "yanlis_alarm"
    return "unknown"


class SpecStoryAligner:
    """
    Faz 2 dual-model çıktılarını çapraz doğrular: Claude çelişkileri GPT ile,
    GPT çelişkileri Claude ile incelenir; nihai rapor üretilir.
    """

    def __init__(self, engine: MultiModelEngine) -> None:
        self._engine = engine

    async def run(
        self,
        dual_model_output: dict[str, Any],
        story_ctx: str,
        spec_ctx: str,
        *,
        report_path: Path | None = None,
    ) -> dict[str, Any]:
        claude_block = dual_model_output.get("claude") or {}
        openai_block = dual_model_output.get("openai") or {}

        claude_sem = claude_block.get("semantic_alignment") or {}
        gpt_sem = openai_block.get("semantic_alignment") or {}
        claude_ta = claude_block.get("test_architecture") or {}
        gpt_ta = openai_block.get("test_architecture") or {}

        claude_contradictions = _extract_contradictions(
            claude_sem if isinstance(claude_sem, dict) else {}
        )
        gpt_contradictions = _extract_contradictions(
            gpt_sem if isinstance(gpt_sem, dict) else {}
        )

        if claude_contradictions:
            gpt_reviews = await asyncio.gather(
                *[
                    self._engine.gpt_peer_review_contradiction(
                        story_ctx=story_ctx,
                        spec_ctx=spec_ctx,
                        contradiction=c,
                    )
                    for c in claude_contradictions
                ],
            )
        else:
            gpt_reviews = []

        if gpt_contradictions:
            claude_reviews = await asyncio.gather(
                *[
                    self._engine.claude_peer_review_contradiction(
                        story_ctx=story_ctx,
                        spec_ctx=spec_ctx,
                        contradiction=c,
                    )
                    for c in gpt_contradictions
                ],
            )
        else:
            claude_reviews = []

        confirmed_claude: list[dict[str, Any]] = []
        false_alarms_claude: list[dict[str, Any]] = []
        inconclusive_claude: list[dict[str, Any]] = []
        for c, review in zip(claude_contradictions, gpt_reviews, strict=True):
            verdict = _normalize_verdict(review)
            row = {
                "source": "claude",
                "original_contradiction": c,
                "reviewer": "openai",
                "review": review,
                "verdict": verdict,
            }
            if verdict == "hata":
                confirmed_claude.append(row)
            elif verdict == "yanlis_alarm":
                false_alarms_claude.append(row)
            else:
                inconclusive_claude.append(row)

        confirmed_gpt: list[dict[str, Any]] = []
        false_alarms_gpt: list[dict[str, Any]] = []
        inconclusive_gpt: list[dict[str, Any]] = []
        for c, review in zip(gpt_contradictions, claude_reviews, strict=True):
            verdict = _normalize_verdict(review)
            row = {
                "source": "openai",
                "original_contradiction": c,
                "reviewer": "claude",
                "review": review,
                "verdict": verdict,
            }
            if verdict == "hata":
                confirmed_gpt.append(row)
            elif verdict == "yanlis_alarm":
                false_alarms_gpt.append(row)
            else:
                inconclusive_gpt.append(row)

        inconsistency_report = {
            "confirmed_inconsistencies": [*confirmed_claude, *confirmed_gpt],
            "false_alarms": [*false_alarms_claude, *false_alarms_gpt],
            "inconclusive_reviews": [*inconclusive_claude, *inconclusive_gpt],
            "peer_review_summary": {
                "claude_contradictions_reviewed_by_gpt": len(claude_contradictions),
                "gpt_contradictions_reviewed_by_claude": len(gpt_contradictions),
            },
        }

        edge_cases = {
            "claude": _extract_edge_cases(
                claude_ta if isinstance(claude_ta, dict) else {}
            ),
            "openai": _extract_edge_cases(
                gpt_ta if isinstance(gpt_ta, dict) else {}
            ),
        }

        logical_gaps = {
            "claude": _extract_logical_gaps(
                claude_sem if isinstance(claude_sem, dict) else {}
            ),
            "openai": _extract_logical_gaps(
                gpt_sem if isinstance(gpt_sem, dict) else {}
            ),
        }

        result: dict[str, Any] = {
            "inconsistency_report": inconsistency_report,
            "edge_cases": edge_cases,
            "logical_gaps": logical_gaps,
        }

        if report_path is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(inconsistency_report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            result["inconsistency_report_path"] = str(report_path.resolve())

        return result


DEFAULT_INCONSISTENCY_REPORT_PATH = (
    Path(__file__).resolve().parent.parent / "uploads" / "inconsistency_report.json"
)


async def execute_alignment_loop(
    dual_model_output: dict[str, Any],
    story_ctx: str,
    spec_ctx: str,
    *,
    engine: MultiModelEngine | None = None,
    save_inconsistency_report: bool = True,
    report_path: Path | str | None = None,
) -> dict[str, Any]:
    """
    Faz 2 `run_dual` çıktısını alır; çelişkileri karşı model ile peer-review eder;
    nihai Inconsistency & Edge Case raporunu döndürür.

    ``save_inconsistency_report`` True ise ``inconsistency_report`` içeriği
    (yalnızca tutarsızlık özeti) JSON dosyasına yazılır.
    """
    eng = engine or MultiModelEngine()
    aligner = SpecStoryAligner(eng)
    path: Path | None = None
    if save_inconsistency_report:
        path = Path(report_path) if report_path else DEFAULT_INCONSISTENCY_REPORT_PATH
    return await aligner.run(
        dual_model_output,
        story_ctx,
        spec_ctx,
        report_path=path,
    )
