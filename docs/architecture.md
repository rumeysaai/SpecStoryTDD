# Architecture

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        SpecStoryTDD                             │
│                                                                 │
│  ┌──────────────┐    ┌──────────────────┐   ┌───────────────┐  │
│  │  User Story  │    │  AlignmentEngine  │   │   LLM (GPT)   │  │
│  │  (Markdown)  │───▶│                  │◀─▶│               │  │
│  └──────────────┘    │  1. Conflict      │   └───────────────┘  │
│                      │     Analysis      │                      │
│  ┌──────────────┐    │  2. Test Suite    │   ┌───────────────┐  │
│  │  OpenAPI     │───▶│     Generation    │──▶│  Pytest Suite │  │
│  │  Spec (JSON) │    │  3. Retry Loop    │   │  (generated)  │  │
│  └──────────────┘    └──────────────────┘   └───────────────┘  │
│                               │                                 │
│                       ┌───────▼──────┐                          │
│                       │  FastAPI     │                          │
│                       │  REST API    │                          │
│                       └──────────────┘                          │
└─────────────────────────────────────────────────────────────────┘
```

## Component Descriptions

### `src/backend/models.py`
Pydantic v2 models that define the data contracts:
- **`AlignmentRequest`** — Input payload (user story + OpenAPI spec + retry config).
- **`Conflict`** — A single detected logical conflict with severity, references, and a fix suggestion.
- **`TestCase`** — An auto-generated Pytest function (name, description, source code).
- **`AlignmentResult`** — Full output (list of conflicts + test suite + summary).

### `src/backend/engine.py` — `AlignmentEngine`
The core async engine:
1. Constructs a structured prompt combining the user story and OpenAPI spec.
2. Invokes the LLM (via LangChain `ChatOpenAI`).
3. Parses and validates the response against `AlignmentResult` (Pydantic).
4. **Feedback-loop retry**: if the response is invalid JSON or fails schema
   validation, the error is appended to the conversation history and the LLM
   is re-prompted — up to `max_retries` times.
5. Transient network/rate-limit errors are handled with exponential back-off
   via `tenacity`.

### `src/backend/config.py`
`pydantic-settings` configuration loaded from environment variables / `.env`.

### `src/backend/api.py`
FastAPI application with:
- `GET /healthz` — liveness probe.
- `POST /analyse` — main analysis endpoint.

## Hybrid TDD/SDD Flow

```
User Story (Markdown)  +  OpenAPI Spec (JSON)
            │
            ▼
    AlignmentEngine.analyse()
            │
     ┌──────┴──────┐
     │             │
  Conflicts    Test Suite
  (JSON)       (Pytest code)
     │             │
     ▼             ▼
  Developer    pytest runner
  reviews &    validates API
  fixes spec   behaviour
```

## Retry Mechanism (Feedback Loop)

```
 Attempt N
     │
     ▼
 LLM call ──▶ raw response
     │
     ▼
 JSON parse ──✗──▶ append error to conversation
     │                       │
     ▼                       ▼
 Pydantic validate    re-prompt LLM (Attempt N+1)
     │
     ▼
 AlignmentResult  ✓
```
