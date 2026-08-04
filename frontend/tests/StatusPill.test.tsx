import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusPill } from "@/components/StatusPill";

describe("StatusPill", () => {
  it("renders a textual status instead of relying on color", () => {
    render(<StatusPill status="READY_WITH_WARNINGS" />);
    expect(screen.getByText("Ready with warnings")).toBeInTheDocument();
  });
});
