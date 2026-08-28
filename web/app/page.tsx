"use client";

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";

const Monaco = dynamic(() => import("@monaco-editor/react"), { ssr: false });

type Run = {
  id: number;
  repo: string;
  ref?: string;
  status: string;
  current_diff?: string | null;
  pr_url?: string | null;
  error?: string | null;
};

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "";

export default function Dashboard() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [health, setHealth] = useState<Record<string, unknown>>({});
  const [selected, setSelected] = useState<Run | null>(null);
  const [socketState, setSocketState] = useState("connecting");
  const [latestEvent, setLatestEvent] = useState<{ title?: string; body?: string } | null>(null);

  useEffect(() => {
    fetch(`${API}/health`)
      .then((res) => res.json())
      .then(setHealth)
      .catch((err) => setHealth({ ok: false, error: String(err) }));

    fetch(`${API}/v1/sandbox/runs`, {
      headers: { "X-API-Key": API_KEY },
    })
      .then((res) => res.json())
      .then((body) => {
        setRuns(body.runs || []);
        if (body.runs?.[0]) setSelected(body.runs[0]);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const wsUrl = API.replace("http", "ws") + `/v1/ws/runs?api_key=${API_KEY}`;
    const socket = new WebSocket(wsUrl);
    socket.onopen = () => setSocketState("live");
    socket.onclose = () => setSocketState("offline");
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (Array.isArray(payload.runs)) {
        setRuns(payload.runs);
        setSelected((prev) => {
          const next = payload.runs.find((run: Run) => run.id === prev?.id);
          return next || prev || payload.runs[0] || null;
        });
      }
      if (payload.event) {
        setLatestEvent(payload.event);
      }
    };
    return () => socket.close();
  }, []);

  const diff = useMemo(
    () => selected?.current_diff || "// No patch diff for this run yet",
    [selected]
  );

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-6xl p-6">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold">AutoPatch Engine</h1>
            <p className="mt-1 text-slate-400">
              Live incident console · websocket {socketState}
              {latestEvent?.title ? ` · ${latestEvent.title}` : ""}
            </p>
          </div>
          <pre className="rounded-lg bg-slate-900 px-4 py-2 text-xs text-slate-300">
            {JSON.stringify(health)}
          </pre>
        </div>

        <div className="mt-8 grid gap-6 lg:grid-cols-2">
          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h2 className="mb-3 text-sm uppercase tracking-wide text-slate-400">
              Runs
            </h2>
            <div className="space-y-2">
              {runs.map((run) => (
                <button
                  key={run.id}
                  onClick={() => setSelected(run)}
                  className={`w-full rounded-lg border px-3 py-2 text-left ${
                    selected?.id === run.id
                      ? "border-emerald-400 bg-emerald-400/10"
                      : "border-slate-800 hover:border-slate-600"
                  }`}
                >
                  <div className="flex justify-between text-sm">
                    <span>#{run.id} {run.repo}</span>
                    <span className="text-slate-400">{run.status}</span>
                  </div>
                  {run.pr_url ? (
                    <a
                      className="text-xs text-emerald-300"
                      href={run.pr_url}
                      target="_blank"
                    >
                      {run.pr_url}
                    </a>
                  ) : null}
                </button>
              ))}
              {runs.length === 0 ? (
                <p className="text-sm text-slate-500">No runs yet.</p>
              ) : null}
            </div>
          </section>

          <section className="overflow-hidden rounded-xl border border-slate-800">
            <div className="border-b border-slate-800 px-4 py-2 text-sm text-slate-400">
              Monaco diff viewer
            </div>
            <Monaco
              height="480px"
              defaultLanguage="diff"
              theme="vs-dark"
              value={diff}
              options={{ readOnly: true, minimap: { enabled: false } }}
            />
          </section>
        </div>
      </div>
    </main>
  );
}
