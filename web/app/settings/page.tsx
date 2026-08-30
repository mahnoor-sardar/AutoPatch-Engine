"use client";

import { API_DISPLAY } from "@/lib/config";
import { useLive } from "@/components/live/LiveProvider";

export default function SettingsPage() {
  const { health, healthError, socket, refresh } = useLive();
  const live = socket === "live";
  return (
    <div>
      <h1 className="page-title">Settings</h1>
      <p className="lede">
        Read-only system information. Approval secrets and OTP controls stay on the Android app.
      </p>

      <div className="panel">
        <h3>Connection</h3>
        <div className="status-row">
          <span>Browser</span>
          <span>Same-origin via Next rewrites</span>
        </div>
        <div className="status-row">
          <span>Backend</span>
          <span className="mono">{API_DISPLAY}</span>
        </div>
      </div>

      <div className="panel">
        <h3>API</h3>
        <div className="status-row">
          <span>Health</span>
          <span className={health?.ok ? "badge ok" : "badge wait"}>
            {health ? (health.ok ? "Operational" : "Degraded") : healthError || "Unavailable"}
          </span>
        </div>
      </div>

      <div className="panel">
        <h3>WebSocket</h3>
        <div className="status-row">
          <span>Runs channel</span>
          <span className={live ? "badge ok" : "badge wait"}>{socket}</span>
        </div>
      </div>

      <div className="panel">
        <h3>Health</h3>
        <div className="status-row">
          <span>Postgres</span>
          <span className={health?.postgres ? "badge ok" : "badge quiet"}>
            {health ? (health.postgres ? "Up" : "Down") : "—"}
          </span>
        </div>
        <div className="status-row">
          <span>Redis</span>
          <span className={health?.redis ? "badge ok" : "badge quiet"}>
            {health ? (health.redis ? "Up" : "Down") : "—"}
          </span>
        </div>
        <button type="button" className="btn" onClick={() => void refresh()} style={{ marginTop: "0.75rem" }}>
          Refresh
        </button>
      </div>

      <div className="panel">
        <h3>Frontend</h3>
        <div className="status-row">
          <span>Package</span>
          <span>autopatch-web</span>
        </div>
        <div className="status-row">
          <span>Runtime</span>
          <span>Next.js 14</span>
        </div>
      </div>
    </div>
  );
}
