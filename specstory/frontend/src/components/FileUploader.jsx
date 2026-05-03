import React, { useCallback, useState } from "react";

const acceptMd = ".md,text/markdown";
const acceptJson = ".json,application/json";

function useDropFile(validator, onFile) {
  const [hover, setHover] = useState(false);
  const [error, setError] = useState("");

  const pick = useCallback(
    (file) => {
      setError("");
      if (!file) return;
      const err = validator(file);
      if (err) {
        setError(err);
        return;
      }
      onFile(file);
    },
    [validator, onFile]
  );

  const onDrop = useCallback(
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      setHover(false);
      const f = e.dataTransfer?.files?.[0];
      pick(f);
    },
    [pick]
  );

  const onDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") setHover(true);
    if (e.type === "dragleave") setHover(false);
  };

  const onInput = (e) => {
    const f = e.target.files?.[0];
    pick(f);
    e.target.value = "";
  };

  return { hover, error, setError, onDrop, onDrag, onInput };
}

function DropPanel({
  label,
  hint,
  file,
  onClear,
  hover,
  error,
  onDrop,
  onDrag,
  onInput,
  accept,
  icon,
}) {
  return (
    <div
      onDrop={onDrop}
      onDragOver={onDrag}
      onDragEnter={onDrag}
      onDragLeave={onDrag}
      className={[
        "relative flex min-h-[160px] flex-col justify-center rounded-xl border-2 border-dashed px-5 py-6 transition-colors",
        hover
          ? "border-accent bg-accent/5"
          : "border-ink-700 bg-ink-900/60 hover:border-mist-400/40",
        error ? "border-red-500/70" : "",
      ].join(" ")}
    >
      <div className="pointer-events-none absolute right-4 top-4 text-2xl opacity-40">{icon}</div>
      <p className="font-display text-lg font-semibold text-mist-100">{label}</p>
      <p className="mt-1 max-w-sm text-sm text-mist-400">{hint}</p>
      {file ? (
        <div className="mt-4 flex items-center justify-between gap-3 rounded-lg bg-ink-800 px-3 py-2">
          <span className="truncate text-sm font-medium text-mist-200">{file.name}</span>
          <button
            type="button"
            onClick={onClear}
            className="pointer-events-auto shrink-0 rounded-md px-2 py-1 text-xs font-medium text-accent hover:bg-accent/10"
          >
            Clear
          </button>
        </div>
      ) : (
        <label className="pointer-events-auto mt-4 inline-flex cursor-pointer items-center gap-2 text-sm font-medium text-accent">
          <span className="rounded-md bg-accent/15 px-3 py-1.5">Browse</span>
          <input type="file" accept={accept} className="hidden" onChange={onInput} />
        </label>
      )}
      {error ? <p className="mt-2 text-xs text-red-400">{error}</p> : null}
    </div>
  );
}

export default function FileUploader({ userStoryFile, specFile, onUserStory, onSpec, disabled }) {
  const validateMd = (f) => {
    if (!f.name.toLowerCase().endsWith(".md")) return "Please choose a .md file.";
    return "";
  };
  const validateJson = (f) => {
    if (!f.name.toLowerCase().endsWith(".json")) return "Please choose a .json file.";
    return "";
  };

  const md = useDropFile(validateMd, onUserStory);
  const js = useDropFile(validateJson, onSpec);

  return (
    <section className="rounded-2xl border border-ink-800 bg-ink-900/40 p-6 shadow-panel backdrop-blur-sm">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="font-display text-xl font-semibold tracking-tight text-mist-100">
            Upload inputs
          </h2>
          <p className="text-sm text-mist-400">
            Drag & drop your Markdown user story and OpenAPI JSON, or browse.
          </p>
        </div>
        <span className="text-xs uppercase tracking-wider text-mist-400">
          {disabled ? "Locked during run" : "Ready"}
        </span>
      </div>
      <div
        className={[
          "mt-6 grid gap-4 md:grid-cols-2",
          disabled ? "pointer-events-none opacity-55" : "",
        ].join(" ")}
      >
        <DropPanel
          label="User story"
          hint="Markdown (.md) — acceptance criteria & business rules."
          file={userStoryFile}
          onClear={() => onUserStory(null)}
          hover={md.hover}
          error={md.error}
          onDrop={disabled ? undefined : md.onDrop}
          onDrag={disabled ? undefined : md.onDrag}
          onInput={disabled ? undefined : md.onInput}
          accept={acceptMd}
          icon="📄"
        />
        <DropPanel
          label="Technical spec"
          hint="OpenAPI contract (.json)."
          file={specFile}
          onClear={() => onSpec(null)}
          hover={js.hover}
          error={js.error}
          onDrop={disabled ? undefined : js.onDrop}
          onDrag={disabled ? undefined : js.onDrag}
          onInput={disabled ? undefined : js.onInput}
          accept={acceptJson}
          icon="{ }"
        />
      </div>
    </section>
  );
}
