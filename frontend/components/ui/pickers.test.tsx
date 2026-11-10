import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ColorInput, normalizeHex } from "./color-input";
import { DateInput } from "./date-input";
import { parseTimeInputValue, TimeInput } from "./time-input";

describe("DateInput calendar", () => {
  function Fixture({ onChange }: { onChange: (value: string) => void }) {
    const [value, setValue] = useState("2026-01-31");
    return (
      <DateInput
        value={value}
        min="2026-01-05"
        onChange={(next) => {
          setValue(next);
          onChange(next);
        }}
      />
    );
  }

  it("opens a month view with the selected day and picks a day", () => {
    const onChange = vi.fn();
    render(<Fixture onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Datum wählen" }));
    const calendar = screen.getByRole("dialog", { name: "Kalender" });
    expect(within(calendar).getByText(/Januar 2026/i)).toBeInTheDocument();
    const selected = within(calendar).getByRole("button", { pressed: true });
    expect(selected).toHaveTextContent("31");
    expect(selected).toHaveFocus();
    // Vor dem Minimum gesperrt
    expect(within(calendar).getByRole("button", { name: /, 4\. Januar 2026$/ })).toBeDisabled();
    fireEvent.click(within(calendar).getByRole("button", { name: /, 15\. Januar 2026$/ }));
    expect(onChange).toHaveBeenLastCalledWith("2026-01-15");
    expect(screen.queryByRole("dialog", { name: "Kalender" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("15.01.2026");
  });

  it("moves with the keyboard, clamps the month end and returns focus on Escape", () => {
    const onChange = vi.fn();
    render(<Fixture onChange={onChange} />);
    const button = screen.getByRole("button", { name: "Datum wählen" });
    fireEvent.click(button);
    const calendar = screen.getByRole("dialog", { name: "Kalender" });
    // 31.1. + 1 Monat = 28.2.2026
    fireEvent.keyDown(within(calendar).getByRole("button", { pressed: true }), { key: "PageDown" });
    expect(within(calendar).getByText(/Februar 2026/i)).toBeInTheDocument();
    expect(document.activeElement).toHaveTextContent("28");
    fireEvent.keyDown(document.activeElement as Element, { key: "ArrowLeft" });
    fireEvent.keyDown(document.activeElement as Element, { key: "Enter" });
    fireEvent.click(document.activeElement as Element);
    expect(onChange).toHaveBeenLastCalledWith("2026-02-27");
    fireEvent.click(button);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Kalender" })).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });
});

describe("TimeInput", () => {
  it("normalises typed times", () => {
    expect(parseTimeInputValue("930")).toBe("09:30");
    expect(parseTimeInputValue("9.30")).toBe("09:30");
    expect(parseTimeInputValue("19:05")).toBe("19:05");
    expect(parseTimeInputValue("9")).toBe("09:00");
    expect(parseTimeInputValue("24:00")).toBeNull();
    expect(parseTimeInputValue("abc")).toBeNull();
  });

  it("commits on blur and offers a quarter-hour list", () => {
    const onChange = vi.fn();
    render(<TimeInput value="" onChange={onChange} aria-label="Zeit" />);
    const field = screen.getByRole("textbox", { name: "Zeit" });
    fireEvent.change(field, { target: { value: "1930" } });
    fireEvent.blur(field);
    expect(onChange).toHaveBeenLastCalledWith("19:30");
    fireEvent.click(screen.getByRole("button", { name: "Uhrzeit wählen" }));
    const list = screen.getByRole("listbox", { name: "Uhrzeit wählen" });
    expect(within(list).getAllByRole("option")).toHaveLength(96);
    fireEvent.click(within(list).getByRole("option", { name: "07:45" }));
    expect(onChange).toHaveBeenLastCalledWith("07:45");
  });
});

describe("ColorInput", () => {
  it("normalises hex values", () => {
    expect(normalizeHex("abc")).toBe("#AABBCC");
    expect(normalizeHex("#12ab34")).toBe("#12AB34");
    expect(normalizeHex("#12ab3")).toBeNull();
  });

  it("changes the color via hex field, swatches and the keyboard", () => {
    const onChange = vi.fn();
    render(<ColorInput value="#336699" aria-label="Akzent" swatches={[{ value: "#FF0000", label: "Rot" }]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Akzent" }));
    const dialog = screen.getByRole("dialog", { name: "Akzent" });
    fireEvent.change(within(dialog).getByLabelText("Hex-Wert"), { target: { value: "#00ff00" } });
    expect(onChange).toHaveBeenLastCalledWith("#00FF00");
    fireEvent.click(within(dialog).getByRole("button", { name: "Rot" }));
    expect(onChange).toHaveBeenLastCalledWith("#FF0000");
    // Nach «Rot» steht der Farbton auf 0, Shift+Pfeil springt um 15°
    const hue = within(dialog).getByRole("slider", { name: "Farbton" });
    fireEvent.keyDown(hue, { key: "ArrowRight", shiftKey: true });
    expect(hue).toHaveAttribute("aria-valuenow", "15");
    expect(onChange.mock.calls.at(-1)![0]).toMatch(/^#[0-9A-F]{6}$/);
  });
});
