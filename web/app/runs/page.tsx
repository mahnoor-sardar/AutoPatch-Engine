"use client";

import { useMemo, useState } from "react";
import { EmptyState, ErrorState, Skeleton } from "@/components/layout/States";
import { useLive } from "@/components/live/LiveProvider";
import { RunRow } from "@/components/runs/RunRow";
import { isActive, isFailed, isWaiting } from "@/lib/utils";

const FILTERS = ["all", "active", "waiting", "completed", "failed"] as const;

export default function RunsPage() {
  const { runs, loading, error, refresh } = useLive();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const [q, setQ] = useState("");

  const filtered = useMemo(() => {
    return runs.filter((run) => {
      if (filter === "active" && !isActive(run)) return false;
      if (filter === "waiting" && !isWaiting(run)) return false;
      if (filter === "completed" && run.status !== "completed") return false;
      if (filter === "failed" && !isFailed(run)) return false;
      if (!q.trim()) return true;
      const hay = `${run.id} ${run.repo} ${run.status} ${run.pipeline_stage || ""}`.toLowerCase();
      return hay.includes(q.trim().toLowerCase());
    });
  }, [runs, filter, q]);

  if (loading) return <Skeleton rows={6} />;
  if (error) return <ErrorState message={error} onRetry={() => void refresh()} />;

  return (
    <div>
      <h1 className="page-title">Runs</h1>
      <p className="lede">Every sandbox incident AutoPatch has tracked.</p>
      <div className="filters" role="tablist" aria-label="Run filters">
        {FILTERS.map((item) => (
          <button
            key={item}
            type="button"
            className={filter === item ? "filter active" : "filter"}
            onClick={() => setFilter(item)}
          >
            {item}
          </button>
        ))}
      </div>
      <input
        className="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search by ID, repository, status, or stage"
        aria-label="Search runs"
      />
      {filtered.length ? (
        <div className="list">
          {filtered.map((run) => (
            <RunRow key={run.id} run={run} />
          ))}
        </div>
      ) : (
        <EmptyState
          title="No runs match"
          body="Adjust filters or wait for GitHub / observability to start a run."
        />
      )}
    </div>
  );
}
