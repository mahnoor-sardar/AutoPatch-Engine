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
  const attempt =
    attempts && attempts > 0 ? attempts : diff ? 1 : 0;
  const value = diff || "// No unified diff has been generated for this run yet.";
  return (
    <div className="panel">
      <h3>Patch attempt #{attempt}</h3>
      <p className="muted" style={{ marginTop: 0 }}>
        {diff ? "Generated · unified diff (source files are not reconstructed)" : "Not generated"}
        {diff
          ? ` · ${stats.files} file${stats.files === 1 ? "" : "s"} · +${stats.insertions} / −${stats.deletions}`
          : ""}
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
        }}
      />
    </div>
  );
}
