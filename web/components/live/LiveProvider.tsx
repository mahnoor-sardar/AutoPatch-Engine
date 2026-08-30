"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  fetchConnectedRepos,
  fetchHealth,
  fetchRecentAudit,
  fetchRuns,
} from "@/lib/api";
import { wsUrl } from "@/lib/config";
import type {
  AgentLogChunk,
  AuditEvent,
  ConnectedRepository,
  Health,
  Run,
  WsPayload,
} from "@/lib/types";

type SocketState = "connecting" | "live" | "reconnecting" | "offline";

/** Keep at most 500 chunks / 120k chars per run so a long stream cannot grow forever. */
export const MAX_AGENT_LOG_CHUNKS = 500;
export const MAX_AGENT_LOG_CHARS = 120_000;

type LiveContextValue = {
  health: Health | null;
  healthError: string | null;
  runs: Run[];
  stats: { total: number; successful: number; running: number; failed: number } | null;
  repos: ConnectedRepository[];
  events: AuditEvent[];
  agentLogs: Record<number, AgentLogChunk[]>;
  socket: SocketState;
  loading: boolean;
  error: string | null;
  latestTitle: string | null;
  refresh: () => Promise<void>;
  mergeAgentLogs: (runId: number, chunks: AgentLogChunk[]) => void;
};

const LiveContext = createContext<LiveContextValue | null>(null);

let ephemeralId = -1;

function mergeRuns(prev: Run[], incoming: Run[]): Run[] {
  const prevById = new Map(prev.map((run) => [run.id, run]));
  const merged = incoming.map((run) => ({
    ...(prevById.get(run.id) || {}),
    ...run,
  }));
  const seen = new Set(incoming.map((run) => run.id));
  const extras = prev.filter((run) => !seen.has(run.id));
  return [...merged, ...extras].sort((a, b) => b.id - a.id);
}

function boundLogs(chunks: AgentLogChunk[]): AgentLogChunk[] {
  let next = chunks.slice(-MAX_AGENT_LOG_CHUNKS);
  let chars = next.reduce((sum, item) => sum + item.chunk.length, 0);
  while (next.length > 1 && chars > MAX_AGENT_LOG_CHARS) {
    chars -= next[0].chunk.length;
    next = next.slice(1);
  }
  return next;
}

function appendLog(
  prev: Record<number, AgentLogChunk[]>,
  chunk: AgentLogChunk
): Record<number, AgentLogChunk[]> {
  const existing = prev[chunk.run_id] || [];
  return {
    ...prev,
    [chunk.run_id]: boundLogs([...existing, chunk]),
  };
}

function applyEventToRuns(runs: Run[], event: NonNullable<WsPayload["event"]>): Run[] {
  if (event.run_id == null) return runs;
  return runs.map((run) => {
    if (run.id !== event.run_id) return run;
    return {
      ...run,
      status: event.status ?? run.status,
      current_diff:
        event.current_diff !== undefined ? event.current_diff : run.current_diff,
      pr_url: event.pr_url !== undefined ? event.pr_url : run.pr_url,
    };
  });
}

export function LiveProvider({ children }: { children: React.ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [stats, setStats] = useState<LiveContextValue["stats"]>(null);
  const [repos, setRepos] = useState<ConnectedRepository[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [agentLogs, setAgentLogs] = useState<Record<number, AgentLogChunk[]>>({});
  const [socket, setSocket] = useState<SocketState>("connecting");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [latestTitle, setLatestTitle] = useState<string | null>(null);
  const delayRef = useRef(1000);

  const loadOptional = useCallback(async () => {
    const [h, repoList, audit] = await Promise.allSettled([
      fetchHealth(),
      fetchConnectedRepos(),
      fetchRecentAudit(200),
    ]);
    if (h.status === "fulfilled") {
      setHealth(h.value);
      setHealthError(null);
    } else {
      setHealthError(
        h.reason instanceof Error ? h.reason.message : "Health check failed"
      );
    }
    if (repoList.status === "fulfilled") {
      setRepos(repoList.value.repositories || []);
    }
    if (audit.status === "fulfilled") {
      setEvents(audit.value.events || []);
    }
  }, []);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const runList = await fetchRuns(100);
      setRuns((prev) => mergeRuns(prev, runList.runs || []));
      setStats(runList.stats || null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load console data");
    }
    await loadOptional();
    setLoading(false);
  }, [loadOptional]);

  const mergeAgentLogs = useCallback((runId: number, chunks: AgentLogChunk[]) => {
    if (!chunks.length) return;
    setAgentLogs((prev) => {
      if ((prev[runId] || []).length) return prev;
      const tagged: AgentLogChunk[] = chunks.map((item) => ({
        ...item,
        run_id: item.run_id || runId,
        stream: item.stream === "stderr" ? "stderr" : "stdout",
      }));
      return { ...prev, [runId]: boundLogs(tagged) };
    });
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const timer = setInterval(() => {
      void loadOptional();
    }, 20000);
    return () => clearInterval(timer);
  }, [loadOptional]);

  useEffect(() => {
    let closed = false;
    let socketRef: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (closed) return;
      if (
        socketRef &&
        (socketRef.readyState === WebSocket.OPEN ||
          socketRef.readyState === WebSocket.CONNECTING)
      ) {
        return;
      }
      setSocket((prev) => (prev === "live" ? "live" : "connecting"));
      const ws = new WebSocket(wsUrl());
      socketRef = ws;
      ws.onopen = () => {
        delayRef.current = 1000;
        setSocket("live");
      };
      ws.onmessage = (message) => {
        let payload: WsPayload;
        try {
          payload = JSON.parse(message.data);
        } catch {
          return;
        }
        if (payload.event?.type === "agent_log") {
          const event = payload.event;
          const runId = event.run_id;
          const chunk = event.chunk;
          if (runId != null && chunk) {
            setAgentLogs((prev) =>
              appendLog(prev, {
                run_id: runId,
                stream: event.stream === "stderr" ? "stderr" : "stdout",
                chunk,
              })
            );
          }
          return;
        }
        if (Array.isArray(payload.runs)) {
          setRuns((prev) => {
            const next = mergeRuns(prev, payload.runs || []);
            return payload.event ? applyEventToRuns(next, payload.event) : next;
          });
        } else if (payload.event) {
          setRuns((prev) => applyEventToRuns(prev, payload.event!));
        }
        if (payload.event) {
          const event = payload.event;
          setLatestTitle(event.title || null);
          setEvents((prev) => {
            const next: AuditEvent = {
              id: ephemeralId,
              run_id: event.run_id ?? null,
              action: event.title || event.type || "event",
              detail: event.body || null,
              actor: "system",
              result: "success",
              created_at: new Date().toISOString(),
              repository:
                payload.runs?.find((run) => run.id === event.run_id)?.repo ?? null,
            };
            ephemeralId -= 1;
            return [next, ...prev.filter((item) => item.id !== next.id)].slice(
              0,
              400
            );
          });
        }
      };
      ws.onclose = () => {
        if (closed) return;
        socketRef = null;
        setSocket("reconnecting");
        timer = setTimeout(connect, delayRef.current);
        delayRef.current = Math.min(delayRef.current * 2, 15000);
      };
    };

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      const current = socketRef;
      socketRef = null;
      if (current && current.readyState < WebSocket.CLOSING) {
        current.close();
      }
    };
  }, []);

  const value = useMemo(
    () => ({
      health,
      healthError,
      runs,
      stats,
      repos,
      events,
      agentLogs,
      socket,
      loading,
      error,
      latestTitle,
      refresh,
      mergeAgentLogs,
    }),
    [
      health,
      healthError,
      runs,
      stats,
      repos,
      events,
      agentLogs,
      socket,
      loading,
      error,
      latestTitle,
      refresh,
      mergeAgentLogs,
    ]
  );

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export function useLive() {
  const ctx = useContext(LiveContext);
  if (!ctx) throw new Error("useLive must be used within LiveProvider");
  return ctx;
}
