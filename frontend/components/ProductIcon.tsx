import type { ReactNode, SVGProps } from "react";
export type IconName = "home" | "jobs" | "applications" | "profile" | "bell" | "menu" | "back" | "filter" | "search" | "check" | "warning" | "clock" | "external" | "chevron" | "pause" | "sparkles" | "document" | "settings" | "shield" | "close" | "sun" | "moon";
const paths: Record<IconName, ReactNode> = {
  home: <><path d="m3 10 9-7 9 7"/><path d="M5 9v11h14V9"/><path d="M9 20v-6h6v6"/></>,
  jobs: <><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18"/></>,
  applications: <><path d="M7 3h10v4H7z"/><path d="M5 5H4v15h16V5h-1M7 12h10M7 16h7"/></>,
  profile: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
  bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/></>,
  menu: <path d="M5 7h14M5 12h14M5 17h14"/>, back: <path d="m15 18-6-6 6-6"/>, filter: <path d="M4 6h16M7 12h10M10 18h4"/>,
  search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>, check: <path d="m5 12 4 4L19 6"/>,
  warning: <><path d="M12 3 2 21h20L12 3Z"/><path d="M12 9v5M12 18h.01"/></>, clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  external: <><path d="M14 4h6v6M20 4l-9 9"/><path d="M18 13v7H4V6h7"/></>, chevron: <path d="m9 18 6-6-6-6"/>, pause: <path d="M9 5v14M15 5v14"/>,
  sparkles: <><path d="m12 3 1 4 4 1-4 1-1 4-1-4-4-1 4-1 1-4Z"/><path d="m5 14 1 3 2 1-2 1-1 2-1-2-2-1 2-1 1-3Z"/></>,
  document: <><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v5h5M9 13h6M9 17h6"/></>, settings: <><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/></>,
  shield: <><path d="M12 3 4 6v6c0 5 3 8 8 9 5-1 8-4 8-9V6l-8-3Z"/><path d="m9 12 2 2 4-4"/></>, close: <path d="m6 6 12 12M18 6 6 18"/>,
  sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></>,
  moon: <path d="M20 15.3A8.5 8.5 0 0 1 8.7 4 8.5 8.5 0 1 0 20 15.3Z"/>,
};
export function ProductIcon({ name, ...props }: { name: IconName } & SVGProps<SVGSVGElement>) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...props}>{paths[name]}</svg>;
}
