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
          <button
            type="button"
            className="btn"
            style={{ marginTop: "0.85rem" }}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "Hide diagnosis" : "View diagnosis"}
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
