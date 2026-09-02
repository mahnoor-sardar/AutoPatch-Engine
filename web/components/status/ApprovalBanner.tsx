"use client";

import type { Run } from "@/lib/types";
import { isWaiting } from "@/lib/utils";

export function ApprovalBanner({ run }: { run: Run }) {
  if (!isWaiting(run)) return null;
  const provision = run.status === "queued" && run.pipeline_stage === "provision";
  const merge = run.status === "awaiting_merge";
  return (
    <section className="banner" role="status">
      <h2>Approval required</h2>
      <p>
        {provision
          ? "Sandbox provision is waiting for approval before clone can start."
          : merge
            ? "The verified patch is waiting for merge approval before a pull request is opened."
            : `Patch attempt #${run.patch_attempts && run.patch_attempts > 0 ? run.patch_attempts : 1} is waiting for review.`}
      </p>
      <p>
        <strong>Why?</strong> AutoPatch will not apply, verify, or open a PR without
        an explicit device approval.
      </p>
      <p>
        <strong>What happens next?</strong> After you approve in the Android
        AutoPatch app, the worker continues the pipeline.
      </p>
      <p style={{ marginBottom: 0 }}>
        <strong>Where?</strong> Review and approve on your Android device. This
        console does not accept OTP or HMAC approval.
      </p>
    </section>
  );
}
