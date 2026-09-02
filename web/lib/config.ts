export const API_BASE =
  typeof window === "undefined"
    ? process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"
    : "";
export const API_DISPLAY =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
export const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "dev-local-key";

export function wsUrl(): string {
  const http = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
  const base = http.replace(/^http/, "ws");
  return `${base}/v1/ws/runs?api_key=${encodeURIComponent(API_KEY)}`;
}

export function authHeaders(): HeadersInit {
  return { "X-API-Key": API_KEY };
}
