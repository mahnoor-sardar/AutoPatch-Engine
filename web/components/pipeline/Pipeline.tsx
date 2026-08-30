"use client";

import { useState } from "react";
import type { PipelineStep } from "@/lib/pipeline";
import { stepHint, type PipelineStepId } from "@/lib/pipeline";

export function Pipeline({
  steps,
  onSelect,
}: {
  steps: PipelineStep[];
  onSelect?: (id: PipelineStepId) => void;
}) {
  const [open, setOpen] = useState<PipelineStepId | null>(null);
  return (
    <div>
      <div className="pipeline" role="list" aria-label="Pipeline">
        {steps.map((step) => (
          <button
            key={step.id}
            type="button"
            className={`step ${step.state}`}
            onClick={() => {
              setOpen(step.id);
              onSelect?.(step.id);
            }}
            aria-pressed={open === step.id}
          >
            <span className="step-node">
              <span className="orb" aria-hidden />
              <span className="step-label">{step.label}</span>
            </span>
          </button>
        ))}
      </div>
      {open ? (
        <p className="muted" style={{ fontSize: "0.85rem" }}>
          <strong>{steps.find((s) => s.id === open)?.label}</strong>
          {" · "}
          {steps.find((s) => s.id === open)?.state.replaceAll("_", " ")}
          {" — "}
          {stepHint(open)}
        </p>
      ) : null}
    </div>
  );
}
