"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { fetchDiagnosis, fetchRun, fetchRunAudit } from "@/lib/api";
import { IncidentSummary } from "@/components/diagnosis/IncidentSummary";
import { EmptyState, ErrorState, Skeleton } from "@/components/layout/States";
import { useLive } from "@/components/live/LiveProvider";
import { PatchViewer } from "@/components/patch/PatchViewer";
import { Pipeline } from "@/components/pipeline/Pipeline";
import { ApprovalBanner } from "@/components/status/ApprovalBanner";
import { StageBadge, StatusBadge } from "@/components/status/StatusBadge";
import { Timeline } from "@/components/timeline/Timeline";
import { pipelineSteps } from "@/lib/pipeline";
import type { AuditEvent, Diagnosis, Run } from "@/lib/types";
import {
  formatDuration,
  parseStackTrace,
  relativeTime,
  runDurationMs,
  statusLabel,
} from "@/lib/utils";

const TABS = ["overview", "details", "timeline", "files"] as const;

export default function RunDetailPage({ params }: { params: { id: string } }) {
  const runId = Number(params.id);
  const { runs } = useLive();
  const live = runs.find((run) => run.id === runId);
  const [detail, setDetail] = useState<Run | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]>("overview");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
  }, [runId]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchRun(runId), fetchRunAudit(runId), fetchDiagnosis(runId)])
      .then(([run, audit, diag]) => {
        if (cancelled) return;
        setDetail(run);
        setEvents(audit.events || []);
        setDiagnosis(diag);
        setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, live?.status, live?.pipeline_stage, live?.current_diff, live?.pr_url]);

  const run = useMemo(() => {
    if (!live && !detail) return null;
    return { ...(detail || {}), ...(live || {}) } as Run;
  }, [live, detail]);

  if (loading && !run) return <Skeleton rows={8} />;
  if (error && !run) return <ErrorState message={error} />;
  if (!run) {
    return (
      <EmptyState
        title="Run not found"
        body="This run is not in the current snapshot. Open it from the runs list."
      />
    );
  }

  const parsed = parseStackTrace(run.stack_trace);
  const steps = pipelineSteps(run, events);
  const duration = runDurationMs(run);

  return (
    <div>
      <p className="eyebrow">
        <Link href="/runs">Runs</Link>
      </p>
      <h1 className="page-title mono">#{run.id}</h1>
      <p className="lede">
        {run.repo}
        {run.ref ? ` · ${run.ref}` : ""}
      </p>

      <div className="health-row">
        <span className="status-chip">
          Status <StatusBadge run={run} />
        </span>
        <span className="status-chip">
          Stage <StageBadge stage={run.pipeline_stage} />
        </span>
        <span className="muted">
          Control {run.control_state ? statusLabel(run.control_state) : "—"}
        </span>
        <span className="muted">Duration {formatDuration(duration)}</span>
        <span className="muted">Attempts {run.patch_attempts ?? 0}</span>
        {run.pr_url ? (
          <a href={run.pr_url} target="_blank" rel="noreferrer">
            Open PR
          </a>
        ) : null}
      </div>

      {run.status === "failed" || run.status === "killed" || run.status === "rejected" ? (
        <section className="banner bad">
          <h2>{statusLabel(run.status)}</h2>
          <p style={{ marginBottom: 0 }}>{run.error || "See the timeline for recorded events."}</p>
        </section>
      ) : null}
      {run.status === "completed" ? (
        <section className="banner ok">
          <h2>Completed</h2>
          <p style={{ marginBottom: 0 }}>
            This run finished{run.finished_at ? ` ${relativeTime(run.finished_at)}` : ""}.
          </p>
        </section>
      ) : null}
      {run.status === "paused" ? (
        <section className="banner">
          <h2>Paused</h2>
          <p style={{ marginBottom: 0 }}>
            Control state is paused. Resume from the Android app.
          </p>
        </section>
      ) : null}
      {run.status === "running" ? (
        <p className="muted">
          <span className="dot live" /> Running — pipeline updates arrive over WebSocket.
        </p>
      ) : null}

      <ApprovalBanner run={run} />

      <div className="tabs" role="tablist">
        {TABS.map((item) => (
          <button
            key={item}
            type="button"
            className={tab === item ? "tab active" : "tab"}
            onClick={() => setTab(item)}
          >
            {item}
          </button>
        ))}
      </div>

      {tab === "overview" ? (
        <>
          <div className="panel">
            <h3>Pipeline</h3>
            <Pipeline steps={steps} />
          </div>
          <div className="grid-2">
            <IncidentSummary
              parsed={parsed}
              diagnosis={diagnosis?.diagnosis}
              error={run.error}
            />
            <div className="panel">
              <h3>Latest context</h3>
              <div className="meta-grid">
                <div>
                  <span>Sandbox</span>
                  {run.e2b_sandbox_id || "—"}
                </div>
                <div>
                  <span>Started</span>
                  {relativeTime(run.started_at)}
                </div>
                <div>
                  <span>Symbols</span>
                  {run.symbol_count ?? "—"}
                </div>
                <div>
                  <span>PR</span>
                  {run.pr_url ? "Opened" : "Not opened"}
                </div>
              </div>
            </div>
          </div>
          {run.current_diff ? (
            <PatchViewer diff={run.current_diff} attempts={run.patch_attempts} />
          ) : null}
        </>
      ) : null}

      {tab === "details" ? (
        <IncidentSummary
          parsed={parsed}
          diagnosis={diagnosis?.diagnosis}
          error={run.error}
        />
      ) : null}

      {tab === "timeline" ? <Timeline events={events} /> : null}

      {tab === "files" ? (
        <PatchViewer diff={run.current_diff} attempts={run.patch_attempts} />
      ) : null}
    </div>
  );
}
