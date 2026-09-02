"use client";

import { ActivityItem } from "@/components/activity/ActivityItem";
import type { AuditEvent } from "@/lib/types";

export function Timeline({ events }: { events: AuditEvent[] }) {
  if (!events.length) {
    return (
      <p className="muted">
        No audit events are recorded for this run yet. AutoPatch does not invent
        missing pipeline steps.
      </p>
    );
  }
  return (
    <div className="stream" role="list">
      {events.map((event) => (
        <div key={event.id} role="listitem">
          <ActivityItem event={event} />
        </div>
      ))}
    </div>
  );
}
