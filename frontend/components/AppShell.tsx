"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useActiveCandidateId } from "@/lib/active-candidate";
import { api } from "@/lib/api";
import { ThemeToggle } from "./ThemeToggle";
import { ProductIcon, type IconName } from "./ProductIcon";

const primaryItems = [
  { label: "Home", path: "/", icon: "home" },
  { label: "Jobs", path: "/jobs", icon: "jobs" },
  { label: "Applications", path: "/applications", icon: "applications" },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const candidateId = useActiveCandidateId();
  const pathname = usePathname() ?? "";
  const [pendingActions, setPendingActions] = useState(0);
  useEffect(() => {
    if (!candidateId) return;
    let active = true;
    api.humanActions(candidateId).then((items) => {
      if (active) setPendingActions(items.filter((item) => item.status === "pending").length);
    }).catch(() => { if (active) setPendingActions(0); });
    return () => { active = false; };
  }, [candidateId]);
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
  const activeFor = (path: string) => path === "/" ? pathname === "/" : pathname.startsWith(path);
  const initials = candidateId.split("_").map((part) => part[0]).join("").slice(0, 2).toUpperCase();
  const navLink = (item: { label: string; path: string; icon: IconName }) => (
    <Link href={hrefFor(item.path)} key={item.path} aria-current={activeFor(item.path) ? "page" : undefined}>
      <ProductIcon name={item.icon} /><span>{item.label}</span>
    </Link>
  );
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="topbar">
        <Link href={hrefFor("/")} className="brand" aria-label="Career OS home">
          <span className="brand-mark" aria-hidden="true">CO</span>
          <span>Career OS</span>
        </Link>
        <nav className="desktop-nav" aria-label="Primary navigation">
          {primaryItems.map(navLink)}
          <Link href={profileHref} aria-current={pathname.startsWith("/candidates/") ? "page" : undefined}><ProductIcon name="profile" /><span>Profile</span></Link>
        </nav>
        <details className="more-menu">
          <summary><ProductIcon name="menu" /> <span>More</span></summary>
          <div className="more-menu-popover">
            <Link href="/candidates">Switch profile</Link>
            <Link href={`/actions${candidateQuery}`}>Action required</Link>
            <Link href={`/settings${candidateQuery}`}>Advanced settings</Link>
            <Link href={`/analytics${candidateQuery}`}>Results</Link>
            <Link href={`/security${candidateQuery}`}>Security diagnostics</Link>
          </div>
        </details>
        <span className="desktop-theme-toggle"><ThemeToggle /></span>
        <span className="environment-label">Active: {candidateId}</span>
        <div className="mobile-header-actions">
          <Link className="icon-button notification-link" href={`/actions${candidateQuery}`} aria-label={pendingActions ? `${pendingActions} actions require attention` : "No actions require attention"}>
            <ProductIcon name="bell" />{pendingActions ? <span className="notification-badge">{pendingActions}</span> : null}
          </Link>
          <ThemeToggle />
          <Link className="candidate-avatar-mini" href={profileHref} aria-label="Open your profile">{initials}</Link>
        </div>
      </header>
      <main id="main-content">{children}</main>
      <nav className="mobile-nav" aria-label="Mobile navigation">
        {primaryItems.map(navLink)}
        <Link href={profileHref} aria-current={pathname.startsWith("/candidates/") ? "page" : undefined}><ProductIcon name="profile" /><span>Profile</span></Link>
      </nav>
      <footer>
        Your application data stays private and every submission remains under your control.
      </footer>
    </div>
  );
}
