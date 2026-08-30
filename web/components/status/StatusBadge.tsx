import type { Run } from "@/lib/types";
import { isWaiting, statusLabel } from "@/lib/utils";

export function StatusBadge({ run }: { run: Run }) {
  const waiting = isWaiting(run);
  const tone = failed(run)
    ? "bad"
    : waiting
      ? "wait"
      : run.status === "completed"
        ? "ok"
        : run.status === "paused"
          ? "wait"
          : "run";
  return (
    <span className={`badge ${tone}`}>
      {waiting ? "Waiting for approval" : statusLabel(run.status)}
    </span>
  );
}

function failed(run: Run) {
  return ["failed", "killed", "rejected"].includes(run.status);
}

export function StageBadge({ stage }: { stage?: string | null }) {
  return <span className="badge quiet">{stage ? statusLabel(stage) : "—"}</span>;
}
