"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useActiveCandidateId } from "@/lib/active-candidate";

const primaryItems = [
  { label: "Home", path: "/" },
  { label: "Jobs", path: "/jobs" },
  { label: "Applications", path: "/applications" },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const candidateId = useActiveCandidateId();
  if (!candidateId) {
    return (
      <main className="page-wrap">
        <section className="panel" role="alert">
          <h1>Invalid profile selection</h1>
          <p>Choose the profile you want to use.</p>
          <Link className="button primary" href="/candidates">Choose profile</Link>
        </section>
      </main>
    );
  }
  const candidateQuery = `?candidate_id=${encodeURIComponent(candidateId)}`;
  const profileHref = `/candidates/${encodeURIComponent(candidateId)}/profile`;
  const hrefFor = (path: string) =>
    path === "/" ? `/${candidateQuery}` : `${path}${candidateQuery}`;
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="topbar">
        <Link href={hrefFor("/")} className="brand" aria-label="Career OS home">
          <span className="brand-mark" aria-hidden="true">CO</span>
          <span>Career OS</span>
        </Link>
        <nav className="desktop-nav" aria-label="Primary navigation">
          {primaryItems.map((item) => <Link href={hrefFor(item.path)} key={item.path}>{item.label}</Link>)}
          <Link href={profileHref}>Profile</Link>
        </nav>
        <details className="more-menu">
          <summary>More</summary>
          <div className="more-menu-popover">
            <Link href="/candidates">Switch profile</Link>
            <Link href={`/actions${candidateQuery}`}>Action required</Link>
            <Link href={`/settings${candidateQuery}`}>Advanced settings</Link>
            <Link href={`/analytics${candidateQuery}`}>Results</Link>
            <Link href={`/security${candidateQuery}`}>Security diagnostics</Link>
          </div>
        </details>
        <span className="environment-label">Active: {candidateId}</span>
      </header>
      <main id="main-content">{children}</main>
      <nav className="mobile-nav" aria-label="Mobile navigation">
        {primaryItems.map((item) => <Link href={hrefFor(item.path)} key={item.path}>{item.label}</Link>)}
        <Link href={profileHref}>Profile</Link>
      </nav>
      <footer>
        Your application data stays private and every submission remains under your control.
      </footer>
    </div>
  );
}
