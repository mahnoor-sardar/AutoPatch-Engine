"use client";

import { useMemo, useState } from "react";
import { ActivityItem } from "@/components/activity/ActivityItem";
import { EmptyState, ErrorState, Skeleton } from "@/components/layout/States";
import { useLive } from "@/components/live/LiveProvider";
import { matchesFilter, type ActivityFilter } from "@/lib/activity";

const FILTERS: ActivityFilter[] = [
  "all",
  "pipeline",
  "approvals",
  "system",
  "github",
  "failures",
];

export default function ActivityPage() {
  const { events, loading, error, refresh } = useLive();
  const [filter, setFilter] = useState<ActivityFilter>("all");
  const filtered = useMemo(
    () => events.filter((event) => matchesFilter(event, filter)),
    [events, filter]
  );

  if (loading) return <Skeleton rows={8} />;
  if (error) return <ErrorState message={error} onRetry={() => void refresh()} />;

  return (
    <div>
      <h1 className="page-title">Activity</h1>
      <p className="lede">
        Complete audit stream across repositories and runs. Expand an event for stored detail.
      </p>
      <div className="filters">
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
      {filtered.length ? (
        <div className="list">
          {filtered.map((event) => (
            <ActivityItem key={event.id} event={event} />
          ))}
        </div>
      ) : (
        <EmptyState
          title="No events in this filter"
          body="The feed only includes events the backend has persisted or pushed over WebSocket."
        />
      )}
    </div>
  );
}
