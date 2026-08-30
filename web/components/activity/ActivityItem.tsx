"use client";

import { useState } from "react";
import { actionTitle, actorLabel, resultLabel } from "@/lib/activity";
import type { AuditEvent } from "@/lib/types";
import { relativeTime } from "@/lib/utils";

export function ActivityItem({
  event,
  compact = false,
}: {
  event: AuditEvent;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <article className="activity-row">
      <button
        type="button"
        className="activity-head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <div>
          <strong>{actionTitle(event.action)}</strong>
          <div className="muted" style={{ fontSize: "0.82rem" }}>
            {event.run_id ? `Run #${event.run_id}` : "System"}
            {event.repository ? ` · ${event.repository}` : ""}
          </div>
        </div>
        <span className="muted">{relativeTime(event.created_at)}</span>
      </button>
      {!compact ? (
        <p className="muted" style={{ margin: "0.35rem 0 0", fontSize: "0.85rem" }}>
          {actorLabel(event.actor, event.device_id)} · {resultLabel(event.result)}
        </p>
      ) : null}
      {open ? (
        <div className="event-expand">
          {event.detail || "No additional detail on this event."}
          {event.metadata ? `\n${JSON.stringify(event.metadata, null, 2)}` : ""}
        </div>
      ) : event.detail && !compact ? (
        <p className="muted" style={{ margin: "0.35rem 0 0", fontSize: "0.85rem" }}>
          {event.detail.length > 160 ? `${event.detail.slice(0, 160)}…` : event.detail}
        </p>
      ) : null}
    </article>
  );
}
