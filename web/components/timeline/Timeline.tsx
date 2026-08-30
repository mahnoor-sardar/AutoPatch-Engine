"use client";

import { useState } from "react";
import { actionTitle, actorLabel, resultLabel } from "@/lib/activity";
import type { AuditEvent } from "@/lib/types";
import { relativeTime } from "@/lib/utils";

export function Timeline({ events }: { events: AuditEvent[] }) {
  const [openId, setOpenId] = useState<number | null>(null);
  if (!events.length) {
    return (
      <p className="muted">
        No audit events are recorded for this run yet. AutoPatch does not invent
        missing pipeline steps.
      </p>
    );
  }
  return (
    <div className="timeline">
      {events.map((event) => (
        <article key={event.id} className="panel" style={{ marginBottom: 0 }}>
          <button
            type="button"
            onClick={() => setOpenId((id) => (id === event.id ? null : event.id))}
            style={{
              width: "100%",
              textAlign: "left",
              background: "none",
              border: 0,
              color: "inherit",
              cursor: "pointer",
              padding: 0,
            }}
          >
            <div className="run-row-top">
              <strong>{actionTitle(event.action)}</strong>
              <span className="muted">{relativeTime(event.created_at)}</span>
            </div>
            <p className="muted" style={{ margin: "0.35rem 0 0" }}>
              {actorLabel(event.actor, event.device_id)} · {resultLabel(event.result)}
            </p>
          </button>
          {openId === event.id ? (
            <pre className="event-expand">{event.detail || "No detail payload."}</pre>
          ) : null}
        </article>
      ))}
    </div>
  );
}
