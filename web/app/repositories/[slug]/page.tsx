"use client";

import { useMemo } from "react";
import Link from "next/link";
import { ActivityItem } from "@/components/activity/ActivityItem";
import { EmptyState } from "@/components/layout/States";
import { useLive } from "@/components/live/LiveProvider";
import { RunRow } from "@/components/runs/RunRow";
import { ownerName, relativeTime } from "@/lib/utils";

export default function RepositoryDetailPage({
  params,
}: {
  params: { slug: string };
}) {
  const fullName = decodeURIComponent(params.slug);
  const { repos, runs, events } = useLive();
  const meta = repos.find((repo) => repo.full_name === fullName);
  const repoRuns = runs.filter((run) => run.repo === fullName);
  const repoEvents = useMemo(
    () =>
      events.filter(
        (event) => event.repository === fullName || repoRuns.some((run) => run.id === event.run_id)
      ),
    [events, fullName, repoRuns]
  );
  const { owner, name } = ownerName(fullName);

  return (
    <div>
      <p className="eyebrow">
        <Link href="/repositories">Repositories</Link>
      </p>
      <h1 className="page-title">{name}</h1>
      <p className="lede">
        {owner}
        {meta ? " · Connected GitHub installation" : " · Appears on sandbox runs"}
      </p>
      <div className="meta-grid">
        <div>
          <span>Status</span>
          {meta ? "Connected" : "Not in connected list"}
        </div>
        <div>
          <span>Default branch</span>
          {meta?.default_branch || repoRuns[0]?.ref || "—"}
        </div>
        <div>
          <span>Installation</span>
          {meta?.installation_id ?? "—"}
        </div>
        <div>
          <span>Last run</span>
          {repoRuns[0] ? `#${repoRuns[0].id} · ${relativeTime(repoRuns[0].started_at)}` : "—"}
        </div>
      </div>
      <h2 className="eyebrow">Runs</h2>
      {repoRuns.length ? (
        <div className="list">
          {repoRuns.map((run) => (
            <RunRow key={run.id} run={run} />
          ))}
        </div>
      ) : (
        <EmptyState title="No runs" body="This repository has no sandbox runs in the current snapshot." />
      )}
      <h2 className="eyebrow" style={{ marginTop: "1.25rem" }}>
        Activity
      </h2>
      {repoEvents.length ? (
        <div className="list">
          {repoEvents.map((event) => (
            <ActivityItem key={event.id} event={event} />
          ))}
        </div>
      ) : (
        <EmptyState title="No repository events" body="Audit events for this repository will appear here." />
      )}
    </div>
  );
}
