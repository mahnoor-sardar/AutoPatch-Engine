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

  if (error && runs.length === 0 && repos.length === 0) {
    return <ErrorState message={error} onRetry={() => void refresh()} />;
  }
  if (loading && runs.length === 0 && repos.length === 0) return <Skeleton rows={5} />;

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
                <div className="repo-grid">
                  <div>
                    <strong>{name}</strong>
                    <p className="muted" style={{ margin: "0.2rem 0 0", fontSize: "0.82rem" }}>
                      {owner}
                      {meta.default_branch ? ` · ${meta.default_branch}` : ""}
                    </p>
                  </div>
                  <span className={meta.connected ? "badge ok" : "badge quiet"}>
                    {meta.connected ? "Connected" : "Seen in runs"}
                  </span>
                </div>
                <p className="muted" style={{ margin: "0.55rem 0 0", fontSize: "0.8rem" }}>
                  Active {repoRuns.filter(isActive).length}
                  {last ? ` · Last run #${last.id}` : ""}
                  {" · "}
                  {relativeTime(lastEvent?.created_at || last?.started_at || last?.finished_at)}
                </p>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
