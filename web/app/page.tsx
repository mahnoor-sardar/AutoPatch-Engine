"use client";

import Link from "next/link";
import { ActivityItem } from "@/components/activity/ActivityItem";
import { EmptyState, ErrorState, Skeleton } from "@/components/layout/States";
import { useLive } from "@/components/live/LiveProvider";
import { IncidentCard } from "@/components/runs/IncidentCard";
import { isActive, isFailed, isWaiting } from "@/lib/utils";

export default function HomePage() {
  const { health, healthError, runs, events, loading, error, refresh, socket } =
    useLive();
  const active = runs.filter(isActive);
  const waiting = runs.filter(isWaiting);
  const completed = runs.filter((run) => run.status === "completed");
  const failed = runs.filter(isFailed);
  const operational = Boolean(health?.ok && health.postgres && health.redis);

  if (error && runs.length === 0) {
    return <ErrorState message={error} onRetry={() => void refresh()} />;
  }
  if (loading && runs.length === 0) return <Skeleton rows={6} />;

  return (
    <div>
      <h1 className="page-title">Overview</h1>
      <p className="lede">What AutoPatch is doing across connected repositories.</p>
      <div className="health-row">
        <div className="health-item">
          <span className={operational ? "dot live" : "dot off"} />
          {operational ? "All systems operational" : "System degraded"}
        </div>
        <div className="health-item">
          <span className={socket === "live" ? "dot live" : "dot off"} />
          WebSocket {socket === "live" ? "connected" : socket}
        </div>
        {healthError ? <span className="muted">{healthError}</span> : null}
      </div>

      <div className="metrics">
        <div className="metric">
          <span>Active</span>
          <strong>{active.length}</strong>
        </div>
        <div className="metric">
          <span>Awaiting</span>
          <strong>{waiting.length}</strong>
        </div>
        <div className="metric">
          <span>Completed</span>
          <strong>{completed.length}</strong>
        </div>
        <div className="metric">
          <span>Failed</span>
          <strong>{failed.length}</strong>
        </div>
      </div>

      <div className="section-head">
        <h2>Active incidents</h2>
        <Link href="/runs">All runs</Link>
      </div>
      {active.length ? (
        <div className="list">
          {active.slice(0, 8).map((run) => (
            <IncidentCard key={run.id} run={run} events={events} />
          ))}
        </div>
      ) : (
        <EmptyState
          title="No active incidents"
          body="When a run is queued, reproducing, or waiting for approval, it appears here."
        />
      )}

      <div className="section-head" style={{ marginTop: "1.35rem" }}>
        <h2>Recent activity</h2>
        <Link href="/activity">Full stream</Link>
      </div>
      {events.length ? (
        <div className="stream">
          {events.slice(0, 8).map((event) => (
            <ActivityItem key={event.id} event={event} compact />
          ))}
        </div>
      ) : (
        <EmptyState
          title="No activity yet"
          body="Audit events from every run will stream here as AutoPatch works."
        />
      )}
    </div>
  );
}
