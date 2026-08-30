import { API_BASE, API_DISPLAY, authHeaders } from "./config";
import type {
  AuditEvent,
  ConnectedRepository,
  Diagnosis,
  Health,
  Run,
  RunListResponse,
} from "./types";

const FETCH_TIMEOUT_MS = 10000;

async function getJson<T>(path: string, withAuth = true): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: withAuth ? authHeaders() : undefined,
      cache: "no-store",
      signal: controller.signal,
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
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new Error(
        `The API at ${API_DISPLAY} did not respond. Confirm the backend is running.`
      );
    }
    if (err instanceof TypeError) {
      throw new Error(
        `Could not reach ${API_BASE}${path}. Check that the backend is running and allows this origin.`
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export function fetchHealth() {
  return getJson<Health>("/health", false);
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
