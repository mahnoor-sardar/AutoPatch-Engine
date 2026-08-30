export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "dev-local-key";

export function wsUrl(): string {
  const base = API_BASE.replace(/^http/, "ws");
  return `${base}/v1/ws/runs?api_key=${encodeURIComponent(API_KEY)}`;
}

export function authHeaders(): HeadersInit {
  return { "X-API-Key": API_KEY };
}
