import React from "react";

const PIPELINE_STEPS = [
  { id: "data_ingesting", short: "Ingest", label: "Data Ingesting…", detail: "Parsing Markdown & OpenAPI context via /analyze." },
  {
    id: "semantic_alignment",
    short: "Align",
    label: "Semantic Alignment in Progress…",
    detail: "Dual-model scan: story vs technical contract (simulated).",
  },
  { id: "gpt_peer_review", short: "Review", label: "GPT Peer-Review…", detail: "Cross-validating contradictions (simulated)." },
  {
    id: "generating_tests",
    short: "Tests",
    label: "Generating Pytest…",
    detail: "Executable test synthesis (simulated until backend wires codegen).",
  },
  { id: "complete", short: "Done", label: "Complete", detail: "Panels below are populated." },
];

const PHASE_ORDER = PIPELINE_STEPS.map((s) => s.id);
const N = PIPELINE_STEPS.length;

function phaseRank(phase) {
  if (phase === "error") return -1;
  if (phase === "idle") return -2;
  if (phase === "complete") return N;
  const i = PHASE_ORDER.indexOf(phase);
  return i >= 0 ? i : -2;
}

/** 0–100: tamamlanan segmentler + aktif adımda kısmi dolgu */
function progressPercent(phase) {
  if (phase === "idle") return 0;
  if (phase === "error") return 0;
  if (phase === "complete") return 100;
  const i = PHASE_ORDER.indexOf(phase);
  if (i < 0) return 0;
  return Math.min(100, ((i + 0.45) / N) * 100);
}

function errorProgressPercent(failedId) {
  const idx = PHASE_ORDER.indexOf(failedId);
  if (idx < 0) return 8;
  return Math.min(100, ((idx + 0.5) / N) * 100);
}

export default function AnalysisStatus({ phase, errorMessage, backendHint, errorAt }) {
  const rank = phaseRank(phase);
  const failedId = errorAt || "data_ingesting";
  const pct = phase === "error" ? errorProgressPercent(failedId) : progressPercent(phase);
  const activeStep = PIPELINE_STEPS.find((s) => s.id === phase) || null;

  return (
    <section className="rounded-2xl border border-ink-800 bg-ink-900/40 p-6 shadow-panel backdrop-blur-sm">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="font-display text-xl font-semibold text-mist-100">Pipeline status</h2>
        {backendHint ? (
          <span className="max-w-[18rem] truncate text-right text-xs text-mist-400">{backendHint}</span>
        ) : null}
      </div>

      {/* Aktif aşama metni */}
      <div className="mt-5 min-h-[3rem]">
        {phase === "idle" ? (
          <p className="text-sm text-mist-500">Upload files and run analysis to start the pipeline.</p>
        ) : phase === "error" ? (
          <p className="text-sm font-medium text-red-300">Pipeline stopped — see error below.</p>
        ) : activeStep ? (
          <>
            <p className="font-medium text-mist-100">{activeStep.label}</p>
            <p className="mt-0.5 text-sm text-mist-500">{activeStep.detail}</p>
          </>
        ) : null}
      </div>

      {/* Yatay progress bar */}
      <div className="mt-5">
        <div
          className={[
            "relative h-3 w-full overflow-hidden rounded-full",
            phase === "error" ? "bg-red-950/50 ring-1 ring-red-500/30" : "bg-ink-800",
          ].join(" ")}
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(pct)}
          aria-label="Analysis pipeline progress"
        >
          <div
            className={[
              "h-full rounded-full transition-[width] duration-500 ease-out",
              phase === "error"
                ? "bg-gradient-to-r from-red-600 to-red-400"
                : "bg-gradient-to-r from-accent to-amber-500",
            ].join(" ")}
            style={{ width: `${pct}%` }}
          />
          {/* Segment ayırıcı çizgiler */}
          <div className="pointer-events-none absolute inset-0 flex">
            {PIPELINE_STEPS.map((_, i) => (
              <div key={i} className="h-full flex-1 border-r border-ink-950/40 last:border-r-0" />
            ))}
          </div>
        </div>

        {/* Adım kısa etiketleri */}
        <div className="mt-3 flex justify-between gap-1 text-[10px] font-semibold uppercase tracking-wider text-mist-500 sm:text-xs">
          {PIPELINE_STEPS.map((step, idx) => {
            const sr = idx;
            const isActive = phase === step.id;
            const isDone = rank > sr;
            const isFailed = phase === "error" && failedId === step.id;
            return (
              <span
                key={step.id}
                className={[
                  "min-w-0 flex-1 truncate text-center",
                  isFailed ? "text-red-400" : isActive ? "text-accent" : isDone ? "text-emerald-400/90" : "",
                ].join(" ")}
                title={step.label}
              >
                {isDone && !isFailed ? "✓ " : ""}
                {isFailed ? "! " : ""}
                {step.short}
              </span>
            );
          })}
        </div>
      </div>

      {phase === "error" && errorMessage ? (
        <div className="mt-4 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {errorMessage}
        </div>
      ) : null}
      {phase === "complete" ? (
        <p className="mt-4 text-sm text-emerald-400/90">
          Ingestion calls the live backend; later stages are simulated until a unified orchestration
          endpoint streams real status.
        </p>
      ) : null}
    </section>
  );
}
