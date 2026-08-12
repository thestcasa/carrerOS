import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";

vi.mock("next/navigation", () => ({ usePathname: () => "/jobs/job-1" }));
vi.mock("@/lib/api", () => ({ api: { humanActions: vi.fn() } }));

describe("responsive application shell", () => {
  beforeEach(() => {
    document.cookie = "careeros_active_candidate=example_candidate; Path=/";
    window.history.replaceState({}, "", "/jobs/job-1");
    vi.mocked(api.humanActions).mockResolvedValue([]);
  });

  it("keeps four candidate-scoped destinations and identifies the active parent route", async () => {
    render(<AppShell><div>Job detail</div></AppShell>);
    const mobile = screen.getByRole("navigation", { name: "Mobile navigation" });
    const links = Array.from(mobile.querySelectorAll("a"));
    expect(links).toHaveLength(4);
    expect(links.map((link) => link.textContent)).toEqual(["Home", "Jobs", "Applications", "Profile"]);
    const jobsLinks = screen.getAllByRole("link", { name: "Jobs" });
    expect(jobsLinks).toHaveLength(2);
    jobsLinks.forEach((link) => {
      expect(link).toHaveAttribute("aria-current", "page");
      expect(link).toHaveAttribute("href", "/jobs?candidate_id=example_candidate");
    });
    expect(mobile.querySelector('a[href*="/actions"]')).not.toBeInTheDocument();
    await waitFor(() => expect(api.humanActions).toHaveBeenCalledWith("example_candidate"));
  });
});
