import type { ParsedStack, Run } from "./types";

export function relativeTime(iso?: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const delta = Date.now() - then;
  const sec = Math.round(delta / 1000);
  if (sec < 10) return "just now";
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  return `${day}d ago`;
}

export function runDurationMs(run: Run): number | null {
  if (run.started_at) {
    const start = new Date(run.started_at).getTime();
    if (Number.isNaN(start)) return run.duration_ms ?? null;
    const end = run.finished_at
      ? new Date(run.finished_at).getTime()
      : Date.now();
    if (!Number.isNaN(end)) return Math.max(0, end - start);
  }
  return run.duration_ms ?? null;
}

export function formatDuration(ms?: number | null): string {
  if (ms == null || ms < 0) return "—";
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

export function parseStackTrace(trace?: string | null): ParsedStack {
  const empty: ParsedStack = {
    exceptionType: null,
    message: null,
    file: null,
    line: null,
    functionName: null,
  };
  if (!trace) return empty;
  const lines = trace.split(/\r?\n/);
  let exceptionType: string | null = null;
  let message: string | null = null;
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const match = lines[i].trim().match(/^([A-Za-z_][\w.]*)(?::\s*(.*))?$/);
    if (!match) continue;
    const name = match[1];
    if (name.endsWith("Error") || name.endsWith("Exception")) {
      exceptionType = name;
      message = match[2] ?? null;
      break;
    }
  }
  let file: string | null = null;
  let line: number | null = null;
  let functionName: string | null = null;
  for (const raw of lines) {
    const py = raw.match(/File "(.+)", line (\d+), in (.+)$/);
    if (py) {
      file = py[1];
      line = Number(py[2]);
      functionName = py[3];
      continue;
    }
    const js = raw.match(/at (?:(.+?) \()?(?:file:\/\/)?([^\s:()]+):(\d+)/);
    if (js) {
      functionName = js[1] || functionName;
      file = js[2];
      line = Number(js[3]);
    }
  }
  return { exceptionType, message, file, line, functionName };
}

export function diffStats(diff?: string | null): {
  files: number;
  insertions: number;
  deletions: number;
} {
  if (!diff) return { files: 0, insertions: 0, deletions: 0 };
  const files = new Set<string>();
  let insertions = 0;
  let deletions = 0;
  for (const line of diff.split(/\r?\n/)) {
    if (line.startsWith("+++ ") && !line.includes("/dev/null")) {
      files.add(line.slice(4).replace(/^b\//, "").split("\t")[0]);
    }
    if (line.startsWith("+") && !line.startsWith("+++")) insertions += 1;
    if (line.startsWith("-") && !line.startsWith("---")) deletions += 1;
  }
  return { files: files.size, insertions, deletions };
}

export function isWaiting(run: Run): boolean {
  return (
    run.status === "awaiting_patch_review" ||
    run.status === "awaiting_merge" ||
    (run.status === "queued" && run.pipeline_stage === "provision")
  );
}

export function isActive(run: Run): boolean {
  return (
    run.status === "running" ||
    run.status === "queued" ||
    isWaiting(run) ||
    run.status === "paused"
  );
}

export function isFailed(run: Run): boolean {
  return ["failed", "killed", "rejected"].includes(run.status);
}

export function ownerName(fullName: string): { owner: string; name: string } {
  const [owner, ...rest] = fullName.split("/");
  return { owner: owner || fullName, name: rest.join("/") || fullName };
}

export function statusLabel(status: string): string {
  return status.replaceAll("_", " ");
}
