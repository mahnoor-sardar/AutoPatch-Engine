"use client";

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { fetchDiagnosis, fetchRun, fetchRunAudit, fetchRunLogs } from "@/lib/api";
import { IncidentSummary } from "@/components/diagnosis/IncidentSummary";
import { EmptyState, ErrorState, Skeleton } from "@/components/layout/States";
import { useLive } from "@/components/live/LiveProvider";
import { AgentLogs } from "@/components/logs/AgentLogs";
import { Pipeline } from "@/components/pipeline/Pipeline";
import { ApprovalBanner } from "@/components/status/ApprovalBanner";
import { StageBadge, StatusBadge } from "@/components/status/StatusBadge";
import { Timeline } from "@/components/timeline/Timeline";
import { pipelineSteps } from "@/lib/pipeline";
import type { AuditEvent, Diagnosis, Run } from "@/lib/types";
import {
  formatDuration,
  isActive,
  parseStackTrace,
  relativeTime,
  runDurationMs,
  statusLabel,
} from "@/lib/utils";

const PatchViewer = dynamic(
  () => import("@/components/patch/PatchViewer").then((mod) => mod.PatchViewer),
  { ssr: false }
);

const TABS = ["overview", "details", "timeline", "files", "logs"] as const;

export default function RunDetailPage({ params }: { params: { id: string } }) {
  const runId = Number(params.id);
  const { runs, events: liveEvents, agentLogs, mergeAgentLogs } = useLive();
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
    Promise.allSettled([
      fetchRun(runId),
      fetchRunAudit(runId),
      fetchDiagnosis(runId),
      fetchRunLogs(runId),
    ])
      .then(([runRes, audit, diag, logs]) => {
        if (cancelled) return;
        if (runRes.status === "fulfilled") {
          setDetail(runRes.value);
          setError(null);
        } else {
          setError(
            runRes.reason instanceof Error
              ? runRes.reason.message
              : "Failed to load this run"
          );
        }
        if (audit.status === "fulfilled") {
          setEvents(audit.value.events || []);
        }
        if (diag.status === "fulfilled") {
          setDiagnosis(diag.value);
        }
        if (logs.status === "fulfilled") {
          mergeAgentLogs(runId, logs.value.chunks || []);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, mergeAgentLogs]);

  const run = useMemo(() => {
    if (!live && !detail) return null;
    return {
      ...(detail || {}),
      ...(live || {}),
      stack_trace: detail?.stack_trace ?? live?.stack_trace,
      e2b_sandbox_id: detail?.e2b_sandbox_id ?? live?.e2b_sandbox_id,
      symbol_count: detail?.symbol_count ?? live?.symbol_count,
    } as Run;
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
  const latest = events[0] || liveEvents.find((event) => event.run_id === run.id);

  return (
    <div>
      <div className="command-head">
        <div>
          <p className="eyebrow">
            <Link href="/runs">Runs</Link>
          </p>
          <h1 className="page-title mono">#{run.id}</h1>
          <p className="lede" style={{ marginBottom: 0 }}>
            {run.repo}
            {run.ref ? ` · ${run.ref}` : ""}
          </p>
        </div>
        <div className="health-row" style={{ margin: 0 }}>
          <StatusBadge run={run} />
          <StageBadge stage={run.pipeline_stage} />
          {run.pr_url ? (
            <a href={run.pr_url} target="_blank" rel="noreferrer" className="badge ok">
              Open PR
            </a>
          ) : null}
        </div>
      </div>

      <div className="incident-meta" style={{ marginBottom: "0.85rem" }}>
        <span>Control {run.control_state ? statusLabel(run.control_state) : "—"}</span>
        <span>Duration {formatDuration(duration)}</span>
        <span>Attempts {run.patch_attempts ?? 0}</span>
        {latest ? <span>Latest {relativeTime(latest.created_at)}</span> : null}
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
          <p style={{ marginBottom: 0 }}>Resume from the Android app.</p>
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
          <IncidentSummary
            parsed={parsed}
            diagnosis={diagnosis?.diagnosis}
            error={run.error}
          />
          <div className="panel">
            <h3>Pipeline</h3>
            <Pipeline steps={steps} />
          </div>
          <div className="panel">
            <h3>What AutoPatch is doing</h3>
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
          <div className="panel">
            <h3>Timeline</h3>
            <Timeline events={events.slice(0, 6)} />
          </div>
          <PatchViewer diff={run.current_diff} attempts={run.patch_attempts} />
          <AgentLogs
            chunks={agentLogs[run.id] || []}
            live={isActive(run)}
          />
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

      {tab === "logs" ? (
        <AgentLogs chunks={agentLogs[run.id] || []} live={isActive(run)} />
      ) : null}
    </div>
  );
}
