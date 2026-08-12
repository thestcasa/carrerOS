import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TagEditor } from "@/components/TagEditor";

describe("TagEditor", () => {
  it("adds and removes array values without changing the API representation", () => {
    const changes = vi.fn();
    function Example() {
      const [roles, setRoles] = useState(["Data Scientist"]);
      return <TagEditor id="roles" label="Target roles" values={roles} onChange={(next) => {
        changes(next);
        setRoles(next);
      }} />;
    }
    render(<Example />);
    const input = screen.getByRole("textbox", { name: "Add target roles" });
    fireEvent.change(input, { target: { value: "ML Engineer" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(changes).toHaveBeenLastCalledWith(["Data Scientist", "ML Engineer"]);
    expect(screen.getByText("ML Engineer")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Remove Data Scientist" }));
    expect(changes).toHaveBeenLastCalledWith(["ML Engineer"]);
  });

  it("does not add empty or duplicate chips", () => {
    const onChange = vi.fn();
    render(<TagEditor id="skills" label="Skills" values={["Python"]} onChange={onChange} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Add skills" }), { target: { value: "Python" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
