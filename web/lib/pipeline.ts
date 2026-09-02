import type { AuditEvent, Run } from "./types";

export type PipelineStepId =
  | "provision"
  | "clone"
  | "reproduce"
  | "diagnose"
  | "patch"
  | "review"
  | "verify"
  | "merge"
  | "pr";

export type StepState =
  | "completed"
  | "active"
  | "waiting"
  | "failed"
  | "idle";

export type PipelineStep = {
  id: PipelineStepId;
  label: string;
  state: StepState;
};

const ORDER: PipelineStepId[] = [
  "provision",
  "clone",
  "reproduce",
  "diagnose",
  "patch",
  "review",
  "verify",
  "merge",
  "pr",
];

function hasAction(events: AuditEvent[], action: string): boolean {
  return events.some((event) => event.action === action);
}

export function pipelineSteps(run: Run, events: AuditEvent[] = []): PipelineStep[] {
  const failed = ["failed", "killed", "rejected"].includes(run.status);
  const stage = run.pipeline_stage || "provision";
  const diagnosed = hasAction(events, "diagnosis");
  const patched = Boolean(run.current_diff) || (run.patch_attempts || 0) > 0;
  const prDone = Boolean(run.pr_url) || hasAction(events, "pr_opened");
  const verified =
    hasAction(events, "pr_opened") ||
    stage === "merge" ||
    stage === "pr" ||
    run.status === "awaiting_merge" ||
    run.status === "completed";

  const currentIndex = ((): number => {
    if (prDone || stage === "pr") return 8;
    if (stage === "merge" || run.status === "awaiting_merge") return 7;
    if (stage === "patch_apply") return 6;
    if (stage === "patch_review" || run.status === "awaiting_patch_review") return 5;
    if (patched && stage !== "clone" && stage !== "provision") return 4;
    if (diagnosed) return 3;
    if (stage === "clone") return 2;
    if (stage === "provision") return 0;
    return Math.max(
      0,
      ORDER.indexOf(stage as PipelineStepId) >= 0
        ? ORDER.indexOf(stage as PipelineStepId)
        : 0
    );
  })();

  return ORDER.map((id, index) => {
    let state: StepState = "idle";
    if (index < currentIndex) state = "completed";
    else if (index === currentIndex) {
      if (failed) state = "failed";
      else if (
        (id === "review" && run.status === "awaiting_patch_review") ||
        (id === "merge" && run.status === "awaiting_merge") ||
        (id === "provision" && run.status === "queued")
      ) {
        state = "waiting";
      } else if (run.status === "paused") state = "waiting";
      else if (run.status === "completed") state = "completed";
      else state = "active";
    }
    if (prDone && id === "pr") state = "completed";
    if (verified && id === "verify" && index < currentIndex) state = "completed";
    const labels: Record<PipelineStepId, string> = {
      provision: "Provision",
      clone: "Clone",
      reproduce: "Reproduce",
      diagnose: "Diagnose",
      patch: "Patch",
      review: "Patch Review",
      verify: "Verify",
      merge: "Merge",
      pr: "PR",
    };
    return { id, label: labels[id], state };
  });
}

export function stepHint(id: PipelineStepId): string {
  const hints: Record<PipelineStepId, string> = {
    provision: "Sandbox is requested and waits for device approval to start.",
    clone: "The repository is cloned into an isolated sandbox.",
    reproduce: "AutoPatch attempts to reproduce the reported failure.",
    diagnose: "The model explains the likely root cause.",
    patch: "A candidate patch is generated as a unified diff.",
    review: "Patch review is gated on the Android AutoPatch app.",
    verify: "The patch is applied and reproduction is re-run.",
    merge: "Merge / PR opening is gated on the Android app.",
    pr: "A GitHub pull request is opened when the merge gate succeeds.",
  };
  return hints[id];
}
