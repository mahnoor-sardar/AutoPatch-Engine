"use client";

import Link from "next/link";
import { StageBadge, StatusBadge } from "@/components/status/StatusBadge";
import type { Run } from "@/lib/types";
import { relativeTime, statusLabel } from "@/lib/utils";

export function RunRow({ run }: { run: Run }) {
  const when = run.started_at || run.finished_at;
  return (
    <Link href={`/runs/${run.id}`} className="run-row">
      <div className="run-row-top">
        <strong className="mono">#{run.id}</strong>
        <span className="muted">{relativeTime(when)}</span>
      </div>
      <div>{run.repo}</div>
      <div className="run-row-top" style={{ marginTop: "0.45rem" }}>
        <StageBadge stage={run.pipeline_stage} />
        <StatusBadge run={run} />
      </div>
      {run.control_state ? (
        <p className="muted" style={{ margin: "0.35rem 0 0", fontSize: "0.8rem" }}>
          Control: {statusLabel(run.control_state)}
        </p>
      ) : null}
    </Link>
  );
}
