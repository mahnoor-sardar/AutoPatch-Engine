"use client";

import { Shell } from "@/components/layout/Shell";
import { LiveProvider } from "@/components/live/LiveProvider";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <LiveProvider>
      <Shell>{children}</Shell>
    </LiveProvider>
  );
}
