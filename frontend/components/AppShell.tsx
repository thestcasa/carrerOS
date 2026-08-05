"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useActiveCandidateId } from "@/lib/active-candidate";

export function AppShell({ children }: { children: ReactNode }) {
  const candidateId = useActiveCandidateId();
  if (!candidateId) {
    return (
      <main className="page-wrap">
        <section className="panel" role="alert">
          <h1>Invalid candidate selection</h1>
          <p>The explicit candidate ID is malformed. Choose a candidate from the candidate list.</p>
          <Link className="button primary" href="/candidates">Select a candidate</Link>
        </section>
      </main>
    );
  }
  const candidateQuery = `?candidate_id=${encodeURIComponent(candidateId)}`;
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link href={`/${candidateQuery}`} className="brand" aria-label="Career OS home">
          <span className="brand-mark" aria-hidden="true">CO</span>
          <span>Career OS</span>
        </Link>
        <nav aria-label="Primary navigation">
          <Link href={`/${candidateQuery}`}>Overview</Link>
          <Link href="/candidates">Candidates</Link>
          <Link href={`/jobs${candidateQuery}`}>Jobs</Link>
          <Link href={`/applications${candidateQuery}`}>Applications</Link>
          <Link href={`/actions${candidateQuery}`}>Actions</Link>
          <Link href={`/security${candidateQuery}`}>Security</Link>
          <Link href={`/analytics${candidateQuery}`}>Analytics</Link>
          <Link href={`/settings${candidateQuery}`}>Settings</Link>
        </nav>
        <span className="environment-label">Active: {candidateId}</span>
      </header>
      <main>{children}</main>
      <footer>
        Local control plane · External submission remains safety-gated
      </footer>
    </div>
  );
}
