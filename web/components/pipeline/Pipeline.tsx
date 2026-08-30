"use client";

import { useState } from "react";
import type { PipelineStep } from "@/lib/pipeline";
import { stepHint, type PipelineStepId } from "@/lib/pipeline";

export function Pipeline({
  steps,
  onSelect,
  compact = false,
  interactive = true,
}: {
  steps: PipelineStep[];
  onSelect?: (id: PipelineStepId) => void;
  compact?: boolean;
  interactive?: boolean;
}) {
  const [open, setOpen] = useState<PipelineStepId | null>(null);

  return (
    <div>
      <div
        className={compact ? "pipeline compact" : "pipeline"}
        role="list"
        aria-label="Pipeline"
      >
        {steps.map((step) => {
          const body = (
            <span className="step-node">
              <span className="orb" aria-hidden />
              <span className="step-label">{step.label}</span>
            </span>
          );
          if (!interactive) {
            return (
              <div
                key={step.id}
                className={`step ${step.state}`}
                role="listitem"
                aria-label={`${step.label}, ${step.state}`}
              >
                {body}
              </div>
            );
          }
          return (
            <button
              key={step.id}
              type="button"
              className={`step ${step.state}`}
              onClick={() => {
                setOpen(step.id);
                onSelect?.(step.id);
              }}
              aria-pressed={open === step.id}
              aria-label={`${step.label}, ${step.state}`}
            >
              {body}
            </button>
          );
        })}
      </div>
      {open && interactive && !compact ? (
        <p className="muted" style={{ fontSize: "0.82rem", margin: "0.15rem 0 0" }}>
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
