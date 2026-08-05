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
          <Link href="/jobs">Jobs</Link>
          <Link href="/applications">Applications</Link>
          <Link href="/actions">Actions</Link>
          <Link href="/security">Security</Link>
          <Link href="/analytics">Analytics</Link>
          <Link href="/settings">Settings</Link>
        </nav>
        <span className="environment-label">Local control plane</span>
      </header>
      <main>{children}</main>
      <footer>
        Local control plane · External submission remains safety-gated
      </footer>
    </div>
  );
}
