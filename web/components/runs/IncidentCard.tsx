"use client";

import Link from "next/link";
import { Pipeline } from "@/components/pipeline/Pipeline";
import { StageBadge, StatusBadge } from "@/components/status/StatusBadge";
import { actionTitle } from "@/lib/activity";
import { pipelineSteps } from "@/lib/pipeline";
import type { AuditEvent, Run } from "@/lib/types";
import { parseStackTrace, relativeTime } from "@/lib/utils";

export function IncidentCard({
  run,
  events = [],
}: {
  run: Run;
  events?: AuditEvent[];
}) {
  const when = run.started_at || run.finished_at;
  const runEvents = events.filter((event) => event.run_id === run.id);
  const latest = runEvents[0];
  const parsed = parseStackTrace(run.stack_trace);
  const incident = parsed.exceptionType || run.error;
  const steps = pipelineSteps(run, runEvents);

  return (
    <Link href={`/runs/${run.id}`} className="run-row incident-card">
      <div className="incident-top">
        <div>
          <strong className="mono">#{run.id}</strong>
          <div style={{ marginTop: "0.18rem" }}>{run.repo}</div>
        </div>
        <span className="muted">{relativeTime(when)}</span>
      </div>
      <div className="incident-meta">
        {run.ref ? <span>{run.ref}</span> : null}
        <StageBadge stage={run.pipeline_stage} />
        <StatusBadge run={run} />
        {run.pr_url ? (
          <span className="badge ok">PR</span>
        ) : null}
      </div>
      <div className="incident-error">
        {incident ? <code>{incident}</code> : <span className="muted">No exception recorded</span>}
        {parsed.message ? <span className="muted"> · {parsed.message}</span> : null}
      </div>
      <Pipeline steps={steps} compact interactive={false} />
      <div className="incident-foot">
        <span>
          {latest
            ? actionTitle(latest.action)
            : "No audit event yet"}
        </span>
        <span>{relativeTime(latest?.created_at || when)}</span>
      </div>
    </Link>
  );
}
