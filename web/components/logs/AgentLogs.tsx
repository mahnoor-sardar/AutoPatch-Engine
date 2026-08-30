"use client";

import { useEffect, useRef } from "react";
import type { AgentLogChunk } from "@/lib/types";

export function AgentLogs({
  chunks,
  live,
}: {
  chunks: AgentLogChunk[];
  live?: boolean;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    const node = scroller.current;
    if (!node || !stick.current) return;
    node.scrollTop = node.scrollHeight;
  }, [chunks]);

  return (
    <div className="panel">
      <h3>Agent logs</h3>
      <p className="muted" style={{ margin: "0 0 0.55rem" }}>
        {live ? "Streaming sandbox stdout/stderr." : "Stored sandbox output for this run."}{" "}
        Cap: 500 chunks / 120k characters per run in the browser.
      </p>
      {chunks.length === 0 ? (
        <p className="muted" style={{ marginBottom: 0 }}>
          No sandbox stdout or stderr is stored for this run yet.
        </p>
      ) : (
        <div
          ref={scroller}
          className="log-scroller"
          onScroll={(event) => {
            const node = event.currentTarget;
            stick.current =
              node.scrollHeight - node.scrollTop - node.clientHeight < 48;
          }}
        >
          {chunks.map((item, index) => (
            <pre
              key={`${item.id ?? "live"}-${item.stream}-${index}`}
              className={`log-line ${item.stream}`}
            >
              <span className="log-tag">{item.stream}</span>
              {item.chunk}
            </pre>
          ))}
        </div>
      )}
    </div>
  );
}
