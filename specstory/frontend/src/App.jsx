import React, { useCallback, useMemo, useState } from "react";
import FileUploader from "./components/FileUploader.jsx";
import AnalysisStatus from "./components/AnalysisStatus.jsx";
import ResultsViewer from "./components/ResultsViewer.jsx";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const API_BASE = import.meta.env.VITE_API_URL || "/api";

function buildDemoResults(analyzePayload) {
  const specSnippet = (analyzePayload?.technical_spec_context || "").split("\n").slice(0, 4).join("\n");
  return {
    inconsistencyReport: {
      confirmed_inconsistencies: [
        {
          source: "claude",
          verdict: "hata",
          original_contradiction: {
            id: "c1",
            description:
              "User story promises “instant / hızlı transfer”; OpenAPI summary shows a 10s timeout on the transfer endpoint — SLA conflict.",
            story_ref: "Acceptance Criteria",
            spec_ref: "POST /transfers",
          },
          review: {
            verdict: "hata",
            rationale:
              "A hard timeout caps latency; “instant” is not satisfied if the story defines instant as sub-second.",
          },
        },
      ],
      false_alarms: [
        {
          source: "claude",
          verdict: "yanlis_alarm",
          original_contradiction: {
            id: "c2",
            description: "Optional header marked required on a single path variant.",
          },
          review: {
            verdict: "yanlis_alarm",
            rationale:
              "Other methods keep the header optional; this is a localized doc inconsistency, not a global story conflict.",
          },
        },
      ],
      inconclusive_reviews: [],
    },
    pytestCode: `import os
import pytest
import httpx

BASE = os.environ.get("SPECSTORY_TEST_BASE_URL", "http://127.0.0.1:8000")


@pytest.mark.parametrize("amount_cents", [0, -1, 9_999_999_999])
def test_transfer_rejects_invalid_amount(amount_cents):
    # Boundary values around balance / amount constraints from spec.
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        r = client.post("/transfers", json={"amount_cents": amount_cents})
        assert r.status_code in (400, 422), r.text


@pytest.mark.parametrize("balance,amount", [(10, 50), (0, 1), (100, 100)])
def test_insufficient_balance_assertions(balance, amount):
    # Explicit assertions for insufficient balance style failures.
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        r = client.post(
            "/transfers",
            json={"from_account": "a", "amount_cents": amount, "balance_hint": balance},
        )
        if amount > balance:
            assert r.status_code in (402, 400, 422), r.text
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if isinstance(body, dict):
                assert "error" in body or "detail" in body or r.status_code == 402
`,
    edgeCases: {
      claude: [
        { case: "Zero / negative transfer amount", rationale: "Must fail validation before balance logic." },
        {
          case: "Timeout vs “hızlı transfer” wording",
          rationale: `Spec excerpt:\\n${specSnippet || "(ingested spec context)"}`,
        },
      ],
      openai: [
        { case: "Maximum balance +1 smallest currency unit", rationale: "Off-by-one at numeric schema max." },
        { case: "Duplicate idempotency key within window", rationale: "Spec retry semantics vs story happy path." },
      ],
    },
  };
}

async function postAnalyze(userStoryFile, specFile) {
  const body = new FormData();
  body.append("user_story", userStoryFile, userStoryFile.name);
  body.append("technical_spec", specFile, specFile.name);
  const res = await fetch(`${API_BASE}/analyze`, { method: "POST", body });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = j.detail?.message || j.detail || JSON.stringify(j);
    } catch {
      try {
        msg = await res.text();
      } catch {
        /* ignore */
      }
    }
    throw new Error(msg || `HTTP ${res.status}`);
  }
  return res.json();
}

export default function App() {
  const [userStoryFile, setUserStoryFile] = useState(null);
  const [specFile, setSpecFile] = useState(null);
  const [phase, setPhase] = useState("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const [errorAt, setErrorAt] = useState(null);
  const [results, setResults] = useState(null);

  const busy = phase !== "idle" && phase !== "complete" && phase !== "error";

  const runPipeline = useCallback(async () => {
    setErrorMessage("");
    setErrorAt(null);
    setResults(null);

    if (!userStoryFile || !specFile) {
      setPhase("error");
      setErrorAt("data_ingesting");
      setErrorMessage("Please upload both a Markdown user story and an OpenAPI JSON file.");
      return;
    }

    try {
      setPhase("data_ingesting");
      const analyzed = await postAnalyze(userStoryFile, specFile);

      setPhase("semantic_alignment");
      await sleep(1200);

      setPhase("gpt_peer_review");
      await sleep(1000);

      setPhase("generating_tests");
      await sleep(900);

      setResults(buildDemoResults(analyzed));
      setPhase("complete");
    } catch (e) {
      setPhase("error");
      setErrorAt("data_ingesting");
      setErrorMessage(e?.message || String(e));
    }
  }, [userStoryFile, specFile]);

  const backendHint = useMemo(() => {
    if (phase === "idle") return "";
    return `API: ${API_BASE}`;
  }, [phase]);

  return (
    <div className="min-h-screen pb-16 pt-10">
      <header className="mx-auto max-w-6xl px-4 sm:px-6">
        <p className="font-display text-sm font-medium uppercase tracking-[0.2em] text-accent">
          SpecStory
        </p>
        <h1 className="mt-2 font-display text-3xl font-semibold tracking-tight text-mist-100 sm:text-4xl">
          Alignment dashboard
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-mist-400">
          Ingest Markdown + OpenAPI, follow semantic alignment & peer-review stages, then inspect
          inconsistencies, generated tests, and edge cases — all in one workspace.
        </p>
      </header>

      <main className="mx-auto mt-10 flex max-w-6xl flex-col gap-8 px-4 sm:px-6">
        <FileUploader
          userStoryFile={userStoryFile}
          specFile={specFile}
          onUserStory={setUserStoryFile}
          onSpec={setSpecFile}
          disabled={busy}
        />

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={runPipeline}
            disabled={busy}
            className={[
              "rounded-xl px-5 py-2.5 font-display text-sm font-semibold tracking-wide transition",
              busy
                ? "cursor-not-allowed bg-ink-800 text-mist-500"
                : "bg-accent text-white shadow-lg shadow-accent/25 hover:bg-accent-muted",
            ].join(" ")}
          >
            {busy ? "Running…" : "Run analysis"}
          </button>
          {phase === "complete" || phase === "error" ? (
            <button
              type="button"
              onClick={() => {
                setPhase("idle");
                setResults(null);
                setErrorMessage("");
                setErrorAt(null);
              }}
              className="rounded-xl border border-ink-700 px-4 py-2 text-sm font-medium text-mist-300 hover:border-mist-400 hover:text-mist-100"
            >
              Reset
            </button>
          ) : null}
        </div>

        <AnalysisStatus
          phase={phase}
          errorMessage={errorMessage}
          backendHint={backendHint}
          errorAt={errorAt}
        />

        {results ? (
          <ResultsViewer
            inconsistencyReport={results.inconsistencyReport}
            pytestCode={results.pytestCode}
            edgeCases={results.edgeCases}
          />
        ) : (
          <section className="rounded-2xl border border-dashed border-ink-700 bg-ink-900/20 px-6 py-12 text-center text-sm text-mist-500">
            Results appear here after a successful run — start with{" "}
            <span className="text-mist-300">Run analysis</span>.
          </section>
        )}
      </main>
    </div>
  );
}
