import type { AuditEvent } from "./types";

export type ActivityFilter =
  | "all"
  | "pipeline"
  | "approvals"
  | "system"
  | "github"
  | "failures";

export function activityCategory(event: AuditEvent): ActivityFilter {
  const action = (event.action || "").toLowerCase();
  if (event.result === "failure" || event.result === "rejected" || action === "expire") {
    return "failures";
  }
  if (
    ["approve", "reject", "expire"].includes(action) ||
    action.includes("approv") ||
    action.includes("review")
  ) {
    return "approvals";
  }
  if (action === "pr_opened" || action.includes("pull request") || /\bpr\b/.test(action)) {
    return "github";
  }
  if (["pause", "resume", "kill"].includes(action) || action.includes("sandbox")) {
    return "system";
  }
  return "pipeline";
}

export function matchesFilter(event: AuditEvent, filter: ActivityFilter): boolean {
  if (filter === "all") return true;
  return activityCategory(event) === filter;
}

export function actionTitle(action: string): string {
  const map: Record<string, string> = {
    approve: "Approval received",
    reject: "Patch rejected",
    expire: "Approval expired",
    diagnosis: "Diagnosis generated",
    pr_opened: "Pull request opened",
    pause: "Run paused",
    resume: "Run resumed",
    kill: "Run killed",
  };
  if (map[action]) return map[action];
  return action.replaceAll("_", " ");
}

export function actorLabel(actor?: string | null, deviceId?: string | null): string {
  if (actor === "android") return "Android";
  if (actor === "worker") return "Worker";
  if (actor === "system") return "System";
  if (deviceId) return "Android";
  return actor || "System";
}

export function resultLabel(result?: string | null): string {
  if (!result) return "—";
  return result.replaceAll("_", " ");
}
