"use client";

import Link from "next/link";
import { EmptyState, ErrorState, Skeleton } from "@/components/layout/States";
import { useLive } from "@/components/live/LiveProvider";
import { isActive, ownerName, relativeTime } from "@/lib/utils";

export default function RepositoriesPage() {
  const { repos, runs, events, loading, error, refresh } = useLive();
  const names = new Map<
    string,
    { connected: boolean; default_branch?: string; installation_id?: number }
  >();
  for (const repo of repos) {
    names.set(repo.full_name, {
      connected: true,
      default_branch: repo.default_branch,
      installation_id: repo.installation_id,
    });
  }
  for (const run of runs) {
    if (!names.has(run.repo)) {
      names.set(run.repo, { connected: false, default_branch: run.ref || undefined });
    }
  }

  if (loading) return <Skeleton rows={5} />;
  if (error) return <ErrorState message={error} onRetry={() => void refresh()} />;

  const rows = [...names.entries()].sort((a, b) => a[0].localeCompare(b[0]));

  return (
    <div>
      <h1 className="page-title">Repositories</h1>
      <p className="lede">
        GitHub installations stored in AutoPatch, plus repositories that already have runs.
      </p>
      {rows.length === 0 ? (
        <EmptyState
          title="No repositories yet"
          body="Install the GitHub App or start a sandbox run to see repositories here. Connection status comes from the database, not invented metrics."
        />
      ) : (
        <div className="list">
          {rows.map(([fullName, meta]) => {
            const { owner, name } = ownerName(fullName);
            const repoRuns = runs.filter((run) => run.repo === fullName);
            const last = repoRuns[0];
            const lastEvent = events.find((event) => event.repository === fullName);
            const href = `/repositories/${encodeURIComponent(fullName)}`;
            return (
              <Link key={fullName} href={href} className="repo-row">
                <div className="run-row-top">
                  <strong>{name}</strong>
                  <span className={meta.connected ? "badge ok" : "badge quiet"}>
                    {meta.connected ? "Connected" : "Seen in runs"}
                  </span>
                </div>
                <p className="muted" style={{ margin: "0.25rem 0" }}>
                  {owner} · GitHub
                  {meta.default_branch ? ` · ${meta.default_branch}` : ""}
                </p>
                <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                  Last activity:{" "}
                  {relativeTime(lastEvent?.created_at || last?.started_at || last?.finished_at)}
                  {" · "}
                  Active runs: {repoRuns.filter(isActive).length}
                  {last ? ` · Last run #${last.id}` : ""}
                </p>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
