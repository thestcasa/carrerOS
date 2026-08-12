import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppShell } from "@/components/AppShell";
import { CandidateCard } from "@/components/CandidateCard";
import { clearActiveCandidate } from "@/lib/active-candidate";

describe("active candidate navigation", () => {
  it("persists a selected candidate and propagates it across operational links", async () => {
    document.cookie = "careeros_active_candidate=; Path=/; Max-Age=0";
    render(
      <AppShell>
        <CandidateCard
          candidate={{
            candidate_id: "fictional_friend",
            display_name: "Fictional Friend",
            profile_version: "0.1.0",
            configuration_status: "valid",
            readiness_status: "not_ready",
            automation_status: "disabled",
          }}
        />
      </AppShell>,
    );

    const editLink = screen.getByRole("link", { name: "Edit profile" });
    editLink.addEventListener("click", (event) => event.preventDefault());
    fireEvent.click(editLink);

    await waitFor(() => expect(screen.getByText("Active: fictional_friend")).toBeVisible());
    expect(screen.getAllByRole("link", { name: "Jobs" })[0]).toHaveAttribute(
      "href",
      "/jobs?candidate_id=fictional_friend",
    );
    expect(screen.getAllByRole("link", { name: "Home" })[0]).toHaveAttribute(
      "href",
      "/?candidate_id=fictional_friend",
    );
    expect(screen.getByRole("link", { name: "Career OS home" })).toHaveAttribute(
      "href",
      "/?candidate_id=fictional_friend",
    );
    expect(document.cookie).toContain("careeros_active_candidate=fictional_friend");
  });

  it("uses a valid explicit query override ahead of the persisted cookie", () => {
    document.cookie = "careeros_active_candidate=fictional_friend; Path=/";
    window.history.replaceState({}, "", "/jobs?candidate_id=query_candidate");

    render(<AppShell><div>content</div></AppShell>);

    expect(screen.getByText("Active: query_candidate")).toBeVisible();
    expect(screen.getAllByRole("link", { name: "Applications" })[0]).toHaveAttribute(
      "href",
      "/applications?candidate_id=query_candidate",
    );
    window.history.replaceState({}, "", "/");
  });

  it("fails safely when the persisted cookie is malformed", () => {
    document.cookie = "careeros_active_candidate=%; Path=/";
    window.history.replaceState({}, "", "/");

    render(<AppShell><div>content</div></AppShell>);

    expect(screen.getByText("Active: example_candidate")).toBeVisible();
    expect(screen.getAllByRole("link", { name: "Home" })[0]).toHaveAttribute(
      "href",
      "/?candidate_id=example_candidate",
    );
  });

  it("denies a malformed explicit query without falling back to the cookie", () => {
    document.cookie = "careeros_active_candidate=fictional_friend; Path=/";
    window.history.replaceState({}, "", "/?candidate_id=../wrong");

    render(<AppShell><div>must not render</div></AppShell>);

    expect(screen.getByRole("alert")).toHaveTextContent("Invalid profile selection");
    expect(screen.queryByText("must not render")).not.toBeInTheDocument();
    expect(screen.queryByText("Active: fictional_friend")).not.toBeInTheDocument();
    window.history.replaceState({}, "", "/");
  });

  it("clears only the matching active candidate cookie", () => {
    document.cookie = "careeros_active_candidate=fictional_friend; Path=/";
    clearActiveCandidate("different_candidate");
    expect(document.cookie).toContain("careeros_active_candidate=fictional_friend");

    clearActiveCandidate("fictional_friend");
    expect(document.cookie).not.toContain("careeros_active_candidate=fictional_friend");
  });
});
