"use client";

import dynamic from "next/dynamic";
import { diffStats } from "@/lib/utils";

const Monaco = dynamic(() => import("@monaco-editor/react"), { ssr: false });

export function PatchViewer({
  diff,
  attempts,
}: {
  diff?: string | null;
  attempts?: number | null;
}) {
  const stats = diffStats(diff);
  const attempt = attempts && attempts > 0 ? attempts : diff ? 1 : 0;
  const value = diff || "// No unified diff has been generated for this run yet.";
  return (
    <div className="panel diff-shell">
      <h3>Patch attempt #{attempt}</h3>
      <p className="muted" style={{ margin: "0 0 0.7rem" }}>
        {diff
          ? `Unified diff · ${stats.files} file${stats.files === 1 ? "" : "s"} · +${stats.insertions} / −${stats.deletions}`
          : "Not generated"}
      </p>
      <Monaco
        height="420px"
        defaultLanguage="diff"
        theme="vs-dark"
        value={value}
        options={{
          readOnly: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          wordWrap: "on",
          padding: { top: 8 },
        }}
      />
    </div>
  );
}
