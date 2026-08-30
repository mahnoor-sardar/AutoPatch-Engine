"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLive } from "@/components/live/LiveProvider";

const ITEMS = [
  { href: "/", label: "Home" },
  { href: "/runs", label: "Runs" },
  { href: "/repositories", label: "Repos" },
  { href: "/activity", label: "Activity" },
  { href: "/settings", label: "Settings" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { socket, latestTitle } = useLive();
  const live = socket === "live";

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
        <p className="side-foot">AI engineering console</p>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">AutoPatch Engine</p>
            {latestTitle ? (
              <p className="latest-event">{latestTitle}</p>
            ) : (
              <p className="latest-event muted">Live incident console</p>
            )}
          </div>
          <div className="conn" aria-live="polite">
            <span className={live ? "dot live" : "dot off"} />
            {live ? "Live" : socket === "reconnecting" ? "Reconnecting…" : "Offline"}
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
