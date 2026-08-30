"use client";

import { API_BASE } from "@/lib/config";
import { useLive } from "@/components/live/LiveProvider";

export default function SettingsPage() {
  const { health, healthError, socket, refresh } = useLive();
  return (
    <div>
      <h1 className="page-title">Settings</h1>
      <p className="lede">
        Read-only system information. Approval secrets and OTP controls stay on the Android app.
      </p>
      <div className="panel">
        <h3>Connection</h3>
        <dl className="dl">
          <dt className="muted">API</dt>
          <dd>{API_BASE}</dd>
          <dt className="muted">WebSocket</dt>
          <dd>{socket}</dd>
          <dt className="muted">Health</dt>
          <dd>
            {health
              ? `ok=${String(health.ok)} postgres=${String(health.postgres)} redis=${String(health.redis)}`
              : healthError || "Unavailable"}
          </dd>
        </dl>
        <button type="button" className="btn" onClick={() => void refresh()}>
          Refresh
        </button>
      </div>
      <div className="panel">
        <h3>Frontend</h3>
        <p className="muted" style={{ marginBottom: 0 }}>
          Next.js 14 console package <code>autopatch-web</code>. No extra configuration is stored in
          this UI.
        </p>
      </div>
    </div>
  );
}
