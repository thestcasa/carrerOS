import Link from "next/link";
import type { ReactNode } from "react";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link href="/" className="brand" aria-label="Career OS home">
          <span className="brand-mark" aria-hidden="true">CO</span>
          <span>Career OS</span>
        </Link>
        <nav aria-label="Primary navigation">
          <Link href="/">Overview</Link>
          <Link href="/candidates">Candidates</Link>
        </nav>
        <span className="environment-label">Local control plane</span>
      </header>
      <main>{children}</main>
      <footer>
        Milestone 1 · No live applications or browser submission enabled
      </footer>
    </div>
  );
}
