import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ThemeToggle } from "@/components/ThemeToggle";

describe("ThemeToggle", () => {
  beforeEach(() => {
    window.localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("switches themes accessibly and persists the candidate preference", async () => {
    render(<ThemeToggle />);
    const toggle = await screen.findByRole("button", { name: "Switch to dark mode" });
    fireEvent.click(toggle);
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(window.localStorage.getItem("careeros-theme")).toBe("dark");
    expect(toggle).toHaveAccessibleName("Switch to light mode");
  });

  it("restores a persisted dark preference", async () => {
    window.localStorage.setItem("careeros-theme", "dark");
    render(<ThemeToggle />);
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", "dark"));
    expect(screen.getByRole("button")).toHaveAccessibleName("Switch to light mode");
  });
});
