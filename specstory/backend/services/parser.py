"""Markdown user story ve OpenAPI JSON'dan LLM için context string üretimi."""

from __future__ import annotations

import json
import re
from typing import Any

# --- User story (Markdown) ---

_HEADING_LINE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _extract_md_section(file_content: str, section_title: str) -> str:
    """İlk eşleşen başlıktan bir sonraki aynı veya daha üst seviye başlığa kadar metni döndürür."""
    if not file_content or not file_content.strip():
        return ""

    title_lower = section_title.strip().lower()
    matches = list(_HEADING_LINE.finditer(file_content))
    for i, m in enumerate(matches):
        level = len(m.group(1))
        raw_title = m.group(2).strip()
        if raw_title.lower() != title_lower:
            continue
        start = m.end()
        end = len(file_content)
        for m2 in matches[i + 1 :]:
            next_level = len(m2.group(1))
            if next_level <= level:
                end = m2.start()
                break
        return file_content[start:end].strip()
    return ""


def parse_user_story(file_content: str) -> str:
    """
    Markdown içinden 'Acceptance Criteria' ve 'Business Rules' bölümlerini ayıklar,
    tek bir LLM context bloğunda birleştirir.
    """
    blocks: list[str] = []
    for label in ("Acceptance Criteria", "Business Rules"):
        body = _extract_md_section(file_content, label)
        if body:
            blocks.append(f"## {label}\n\n{body}")

    if blocks:
        return "\n\n---\n\n".join(blocks)

    return (
        "[Uyarı: 'Acceptance Criteria' veya 'Business Rules' başlıkları "
        "bulunamadı. Ham metnin özeti aşağıdadır.]\n\n"
        + file_content.strip()
    )


# --- OpenAPI ---

_CONSTRAINT_KEYS = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
    "multipleOf",
    "format",
    "enum",
    "const",
    "default",
)


def _resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any] | None:
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return None
    node: Any = root
    for part in ref.removeprefix("#/").split("/"):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node if isinstance(node, dict) else None


def _deref_schema(root: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in schema:
        resolved = _resolve_ref(root, schema["$ref"])
        if resolved:
            out = {k: v for k, v in resolved.items() if k != "$ref"}
            for k, v in schema.items():
                if k != "$ref":
                    out[k] = v
            return out
    return schema


def _format_constraints(schema: dict[str, Any], indent: str = "") -> list[str]:
    lines: list[str] = []
    for key in _CONSTRAINT_KEYS:
        if key not in schema:
            continue
        val = schema[key]
        if key == "enum" and isinstance(val, list) and len(val) > 20:
            val = val[:20] + ["…"]
        lines.append(f"{indent}{key}: {json.dumps(val, ensure_ascii=False)}")
    return lines


def _collect_schema_constraints(
    root: dict[str, Any],
    schema: dict[str, Any],
    prefix: str = "",
    depth: int = 0,
    max_depth: int = 8,
) -> list[str]:
    if depth > max_depth:
        return [f"{prefix}… (max derinlik)"]

    s = _deref_schema(root, schema)
    out: list[str] = []
    out.extend(_format_constraints(s, prefix))

    if "properties" in s and isinstance(s["properties"], dict):
        for prop_name, prop_schema in s["properties"].items():
            if not isinstance(prop_schema, dict):
                continue
            pfx = f"{prefix}{prop_name}." if prefix else f"{prop_name}."
            out.extend(
                _collect_schema_constraints(root, prop_schema, pfx, depth + 1, max_depth)
            )

    items = s.get("items")
    if isinstance(items, dict):
        out.extend(_collect_schema_constraints(root, items, f"{prefix}items.", depth + 1, max_depth))
    elif isinstance(items, list):
        for idx, it in enumerate(items):
            if isinstance(it, dict):
                out.extend(
                    _collect_schema_constraints(
                        root, it, f"{prefix}items[{idx}].", depth + 1, max_depth
                    )
                )

    for comb in ("oneOf", "anyOf", "allOf"):
        opts = s.get(comb)
        if isinstance(opts, list):
            for idx, opt in enumerate(opts):
                if isinstance(opt, dict):
                    out.extend(
                        _collect_schema_constraints(
                            root, opt, f"{prefix}{comb}[{idx}].", depth + 1, max_depth
                        )
                    )

    return out


def _summarize_parameter(root: dict[str, Any], param: dict[str, Any]) -> list[str]:
    name = param.get("name", "?")
    loc = param.get("in", "?")
    required = param.get("required", False)
    header = f"- Parameter `{name}` (in: {loc}, required: {required})"
    lines = [header]
    schema = param.get("schema")
    if isinstance(schema, dict):
        lines.extend(_collect_schema_constraints(root, schema, prefix="  schema."))
    return lines


def parse_openapi_spec(file_content: dict[str, Any]) -> str:
    """
    OpenAPI (3.x) spec sözlüğünü gezerek endpoint'ler, HTTP metodları ve
    parameters / schema altındaki teknik kısıtları özet metne çevirir.
    """
    lines: list[str] = []
    paths = file_content.get("paths")
    if not isinstance(paths, dict):
        return "[OpenAPI: paths bulunamadı veya geçersiz.]"

    http_methods = frozenset(
        {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
    )

    for path_key, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        path_level_params = path_item.get("parameters") or []
        if not isinstance(path_level_params, list):
            path_level_params = []

        for method, operation in path_item.items():
            if method.lower() not in http_methods:
                continue
            if not isinstance(operation, dict):
                continue

            op_id = operation.get("operationId", "")
            summary = operation.get("summary", "")
            lines.append(f"## {method.upper()} {path_key}")
            if op_id:
                lines.append(f"operationId: {op_id}")
            if summary:
                lines.append(f"summary: {summary}")

            merged_params: list[dict[str, Any]] = []
            for p in path_level_params:
                if isinstance(p, dict):
                    merged_params.append(p)
            for p in operation.get("parameters") or []:
                if isinstance(p, dict):
                    merged_params.append(p)

            if merged_params:
                lines.append("parameters:")
                for p in merged_params:
                    lines.extend(_summarize_parameter(file_content, p))

            rb = operation.get("requestBody")
            if isinstance(rb, dict):
                content = rb.get("content")
                if isinstance(content, dict):
                    lines.append("requestBody:")
                    for ct, media in content.items():
                        if not isinstance(media, dict):
                            continue
                        sch = media.get("schema")
                        if isinstance(sch, dict):
                            lines.append(f"  content-type: {ct}")
                            lines.extend(
                                _collect_schema_constraints(file_content, sch, prefix="    ")
                            )

            for code, resp in (operation.get("responses") or {}).items():
                if not isinstance(resp, dict):
                    continue
                desc = resp.get("description", "")
                lines.append(f"response {code}: {desc}")
                content = resp.get("content")
                if isinstance(content, dict):
                    for ct, media in content.items():
                        if not isinstance(media, dict):
                            continue
                        sch = media.get("schema")
                        if isinstance(sch, dict):
                            lines.append(f"  content-type: {ct}")
                            lines.extend(
                                _collect_schema_constraints(file_content, sch, prefix="    ")
                            )

            lines.append("")

    return "\n".join(lines).strip() or "[OpenAPI: işlenebilir operasyon bulunamadı.]"
