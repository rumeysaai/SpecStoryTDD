import React from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";

function severityCard(item) {
  if (item._kind === "inconclusive") {
    return {
      border: "border-yellow-500/35",
      bg: "bg-yellow-500/5",
      badge: "bg-yellow-500/15 text-yellow-100",
      label: "Needs review",
    };
  }
  const verdict = String(item?.verdict || "").toLowerCase();
  const isFalse = verdict === "yanlis_alarm" || verdict === "false_alarm";
  if (isFalse || item._kind === "false_alarm") {
    return {
      border: "border-amber-500/40",
      bg: "bg-amber-500/5",
      badge: "bg-amber-500/20 text-amber-200",
      label: "Warning",
    };
  }
  return {
    border: "border-red-500/45",
    bg: "bg-red-500/5",
    badge: "bg-red-500/20 text-red-200",
    label: "Inconsistency",
  };
}

function InconsistencyColumn({ report }) {
  const confirmed = report?.confirmed_inconsistencies || [];
  const falseAlarms = report?.false_alarms || [];
  const inconclusive = report?.inconclusive_reviews || [];

  const cards = [
    ...confirmed.map((c) => ({ ...c, _kind: "confirmed" })),
    ...falseAlarms.map((c) => ({ ...c, _kind: "false_alarm" })),
    ...inconclusive.map((c) => ({ ...c, _kind: "inconclusive" })),
  ];

  if (!cards.length) {
    return (
      <div className="rounded-xl border border-ink-700 bg-ink-950/50 p-6 text-sm text-mist-500">
        No inconsistency items yet. Run an analysis or connect the full alignment API.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {cards.map((row, i) => {
        const orig = row.original_contradiction || row;
        const desc = orig.description || orig.rationale || JSON.stringify(orig);
        const style = severityCard(row);
        const title =
          row._kind === "false_alarm"
            ? "Peer review: likely false alarm"
            : row._kind === "inconclusive"
              ? "Inconclusive review"
              : "Confirmed inconsistency";
        return (
          <article
            key={i}
            className={`rounded-xl border ${style.border} ${style.bg} p-4 shadow-inner`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${style.badge}`}>
                {style.label}
              </span>
              <span className="text-[10px] uppercase tracking-wider text-mist-500">
                {row.source || "unknown"}
              </span>
            </div>
            <h4 className="mt-2 font-display text-sm font-semibold text-mist-100">{title}</h4>
            <p className="mt-1 text-sm leading-relaxed text-mist-300">{desc}</p>
            {row.review?.rationale ? (
              <p className="mt-2 border-t border-ink-700 pt-2 text-xs text-mist-400">
                <span className="font-medium text-mist-300">Reviewer: </span>
                {row.review.rationale}
              </p>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}

function EdgeCaseColumn({ edgeCases }) {
  const left = edgeCases?.claude || [];
  const right = edgeCases?.openai || [];
  const merged = [
    ...left.map((e) => ({ ...e, _from: "Claude" })),
    ...right.map((e) => ({ ...e, _from: "GPT" })),
  ];

  if (!merged.length) {
    return (
      <p className="text-sm text-mist-500">No edge cases in the last run. They appear after alignment output.</p>
    );
  }

  return (
    <ul className="space-y-3">
      {merged.map((e, i) => (
        <li
          key={i}
          className="rounded-lg border border-ink-700 bg-ink-950/60 px-3 py-2.5 text-sm text-mist-200"
        >
          <span className="text-[10px] font-semibold uppercase tracking-wider text-accent">
            {e._from}
          </span>
          <p className="mt-1 font-medium text-mist-100">{e.case || e.title || "Edge case"}</p>
          {e.rationale ? <p className="mt-1 text-xs text-mist-400">{e.rationale}</p> : null}
        </li>
      ))}
    </ul>
  );
}

export default function ResultsViewer({ inconsistencyReport, pytestCode, edgeCases }) {
  const code = pytestCode || "# No generated tests yet.\n";

  return (
    <section className="rounded-2xl border border-ink-800 bg-ink-900/40 p-6 shadow-panel backdrop-blur-sm">
      <h2 className="font-display text-xl font-semibold text-mist-100">Results</h2>
      <p className="mt-1 text-sm text-mist-400">Three-pane layout — inconsistency, code, edge cases.</p>

      <div className="mt-6 grid min-h-[420px] gap-4 xl:grid-cols-3">
        <div className="flex min-h-0 flex-col rounded-xl border border-ink-800 bg-ink-950/40 p-4">
          <h3 className="font-display text-sm font-semibold uppercase tracking-wider text-mist-400">
            Inconsistency report
          </h3>
          <div className="mt-3 max-h-[min(70vh,560px)] flex-1 overflow-y-auto pr-1">
            <InconsistencyColumn report={inconsistencyReport} />
          </div>
        </div>

        <div className="flex min-h-0 min-w-0 flex-col rounded-xl border border-ink-800 bg-ink-950/40 p-4">
          <h3 className="font-display text-sm font-semibold uppercase tracking-wider text-mist-400">
            Generated Pytest
          </h3>
          <div className="mt-3 max-h-[min(70vh,560px)] flex-1 overflow-auto rounded-lg border border-ink-700">
            <SyntaxHighlighter
              language="python"
              style={vscDarkPlus}
              customStyle={{
                margin: 0,
                borderRadius: "0.5rem",
                fontSize: "12px",
                lineHeight: 1.55,
                background: "#0d1117",
              }}
              showLineNumbers
              wrapLines
            >
              {code}
            </SyntaxHighlighter>
          </div>
        </div>

        <div className="flex min-h-0 flex-col rounded-xl border border-ink-800 bg-ink-950/40 p-4">
          <h3 className="font-display text-sm font-semibold uppercase tracking-wider text-mist-400">
            Edge case breakdown
          </h3>
          <div className="mt-3 max-h-[min(70vh,560px)] flex-1 overflow-y-auto pr-1">
            <EdgeCaseColumn edgeCases={edgeCases} />
          </div>
        </div>
      </div>
    </section>
  );
}
