import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Select } from "./select";

function Fixture({ onChange = vi.fn() }: { onChange?: (value: string) => void }) {
  const [value, setValue] = useState("b");
  return (
    <label>
      <span>Farbe</span>
      <Select
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          onChange(event.target.value);
        }}
      >
        <option value="a">Apfel</option>
        <option value="b">Birne</option>
        <optgroup label="Mehr">
          <option value="c" disabled>
            Citrone
          </option>
          <option value="d">Dattel</option>
        </optgroup>
      </Select>
    </label>
  );
}

const field = () => screen.getByRole("combobox", { name: "Farbe" });

describe("Select", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("opens its own list on click and selects with a normal change event", () => {
    const onChange = vi.fn();
    render(<Fixture onChange={onChange} />);
    fireEvent.mouseDown(field());
    const list = screen.getByRole("listbox");
    expect(field()).toHaveAttribute("aria-expanded", "true");
    expect(within(list).getAllByRole("option").map((item) => item.textContent)).toEqual(["Apfel", "Birne✓", "Citrone", "Dattel"]);
    expect(within(list).getByText("Mehr")).toBeInTheDocument();
    expect(within(list).getByRole("option", { name: /Birne/ })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(within(list).getByRole("option", { name: "Dattel" }));
    expect(onChange).toHaveBeenCalledWith("d");
    expect(field()).toHaveValue("d");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("ignores disabled options", () => {
    const onChange = vi.fn();
    render(<Fixture onChange={onChange} />);
    fireEvent.mouseDown(field());
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "Citrone" }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("listbox")).toBeInTheDocument();
  });

  it("is operated with the keyboard and skips disabled options", () => {
    const onChange = vi.fn();
    render(<Fixture onChange={onChange} />);
    fireEvent.keyDown(field(), { key: "ArrowDown" });
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(field(), { key: "ArrowDown" });
    expect(field()).toHaveAttribute("aria-activedescendant", within(screen.getByRole("listbox")).getByRole("option", { name: "Dattel" }).id);
    fireEvent.keyDown(field(), { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("d");
    fireEvent.keyDown(field(), { key: " " });
    fireEvent.keyDown(field(), { key: "a" });
    fireEvent.keyDown(field(), { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith("a");
  });

  it("closes with Escape without changing the value", () => {
    const onChange = vi.fn();
    render(<Fixture onChange={onChange} />);
    fireEvent.mouseDown(field());
    fireEvent.keyDown(field(), { key: "ArrowDown" });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
    expect(field()).toHaveValue("b");
  });

  it("keeps the native picker on touch devices", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query === "(pointer: coarse)", addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    render(<Fixture />);
    fireEvent.mouseDown(field());
    fireEvent.keyDown(field(), { key: "ArrowDown" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
