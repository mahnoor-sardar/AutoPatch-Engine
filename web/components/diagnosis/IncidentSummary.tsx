"use client";

import { useState } from "react";
import type { ParsedStack } from "@/lib/types";

export function IncidentSummary({
  parsed,
  diagnosis,
  error,
}: {
  parsed: ParsedStack;
  diagnosis?: string | null;
  error?: string | null;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="panel">
      <h3>What happened?</h3>
      <dl className="dl">
        <dt className="muted">Exception</dt>
        <dd>{parsed.exceptionType || error || "Unknown"}</dd>
        <dt className="muted">Message</dt>
        <dd>{parsed.message || "—"}</dd>
        <dt className="muted">File</dt>
        <dd>{parsed.file || "—"}</dd>
        <dt className="muted">Line</dt>
        <dd>{parsed.line ?? "—"}</dd>
        <dt className="muted">Function</dt>
        <dd>{parsed.functionName || "—"}</dd>
      </dl>
      {diagnosis ? (
        <>
          <p className="muted" style={{ margin: "0.7rem 0 0", fontSize: "0.84rem" }}>
            {open
              ? null
              : diagnosis.length > 280
                ? `${diagnosis.slice(0, 280).trim()}…`
                : diagnosis}
          </p>
          <button
            type="button"
            className="btn"
            style={{ marginTop: "0.7rem" }}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "Hide full diagnosis" : "View full diagnosis"}
          </button>
          {open ? <pre className="event-expand">{diagnosis}</pre> : null}
        </>
      ) : (
        <p className="muted" style={{ marginBottom: 0 }}>
          No diagnosis event is stored for this run yet.
        </p>
      )}
    </div>
  );
}
