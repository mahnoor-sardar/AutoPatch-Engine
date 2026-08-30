"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLive } from "@/components/live/LiveProvider";
import { isWaiting } from "@/lib/utils";

const ITEMS = [
  { href: "/", label: "Home" },
  { href: "/runs", label: "Runs" },
  { href: "/repositories", label: "Repos" },
  { href: "/activity", label: "Activity" },
  { href: "/settings", label: "Settings" },
];

function headerContext(pathname: string): string {
  if (pathname === "/") return "Overview";
  if (pathname === "/runs") return "Runs";
  const run = pathname.match(/^\/runs\/(\d+)/);
  if (run) return `Run #${run[1]}`;
  if (pathname === "/repositories") return "Repositories";
  if (pathname.startsWith("/repositories/")) {
    try {
      return decodeURIComponent(pathname.split("/").slice(2).join("/"));
    } catch {
      return "Repository";
    }
  }
  if (pathname === "/activity") return "Activity";
  if (pathname === "/settings") return "Settings";
  return "Live incident console";
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { socket, latestTitle, runs } = useLive();
  const live = socket === "live";
  const waiting = runs.filter(isWaiting).length;
  const connClass =
    live ? "conn live" : socket === "reconnecting" ? "conn reconnecting" : "conn";
  const context = headerContext(pathname);

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Primary">
        <Link href="/" className="brand">
          <span className="brand-mark" aria-hidden />
          AUTOPATCH
        </Link>
        <nav className="side-nav">
          {ITEMS.map((item) => {
            const active =
              item.href === "/"
                ? pathname === "/"
                : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={active ? "nav-link active" : "nav-link"}
                aria-current={active ? "page" : undefined}
              >
                {item.label === "Repos" ? "Repositories" : item.label}
              </Link>
            );
          })}
        </nav>
        <p className="side-foot">Incident command center</p>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">{context}</p>
            {latestTitle ? (
              <p className="latest-event">{latestTitle}</p>
            ) : (
              <p className="latest-event muted">Waiting for the next audit event</p>
            )}
          </div>
          <div className="header-stats">
            {waiting > 0 ? <span>{waiting} waiting</span> : null}
            <div className={connClass} aria-live="polite">
              <span className={live ? "dot live" : "dot off"} />
              {live
                ? "Live"
                : socket === "reconnecting"
                  ? "Reconnecting…"
                  : socket === "connecting"
                    ? "Connecting…"
                    : "Offline"}
            </div>
          </div>
        </header>
        <main className="main">{children}</main>
        <nav className="bottom-nav" aria-label="Mobile">
          {ITEMS.map((item) => {
            const active =
              item.href === "/"
                ? pathname === "/"
                : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={active ? "bottom-link active" : "bottom-link"}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
