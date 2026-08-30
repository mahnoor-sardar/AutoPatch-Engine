import { API_BASE, authHeaders } from "./config";
import type {
  AuditEvent,
  ConnectedRepository,
  Diagnosis,
  Health,
  Run,
  RunListResponse,
} from "./types";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: authHeaders(),
    cache: "no-store",
  });
  if (!response.ok) {
    if (response.status === 401) {
      throw new Error(
        "Unauthorized. Set NEXT_PUBLIC_API_KEY to the same value as the backend API key."
      );
    }
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export function fetchHealth() {
  return getJson<Health>("/health");
}

export function fetchRuns(limit = 100) {
  return getJson<RunListResponse>(`/v1/sandbox/runs?limit=${limit}`);
}

export function fetchRun(id: number) {
  return getJson<Run>(`/v1/sandbox/runs/${id}`);
}

export function fetchRunAudit(id: number) {
  return getJson<{ events: AuditEvent[] }>(`/v1/sandbox/runs/${id}/audit`);
}

export function fetchRecentAudit(limit = 200) {
  return getJson<{ events: AuditEvent[] }>(`/v1/sandbox/audit?limit=${limit}`);
}

export function fetchDiagnosis(id: number) {
  return getJson<Diagnosis>(`/v1/sandbox/runs/${id}/diagnosis`);
}

export function fetchConnectedRepos() {
  return getJson<{ repositories: ConnectedRepository[] }>(
    "/v1/github/connected"
  );
}
