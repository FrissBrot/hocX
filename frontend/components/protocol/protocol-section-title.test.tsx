import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProtocolSectionTitle } from "./protocol-section-title";

function setup(overrides: Partial<Parameters<typeof ProtocolSectionTitle>[0]> = {}) {
  const props = {
    elementId: "e-1",
    number: 3,
    title: "Kasse",
    templateTitle: null,
    hidden: false,
    canRename: true,
    canToggleHidden: true,
    onRename: vi.fn().mockResolvedValue(true),
    onToggleHidden: vi.fn(),
    ...overrides,
  };
  render(<ProtocolSectionTitle {...props} />);
  return props;
}

describe("ProtocolSectionTitle", () => {
  it("zeigt die Nummer zweistellig und den Titel als Überschrift", () => {
    setup();
    expect(screen.getByText("03")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Punkt 3 Kasse" })).toBeInTheDocument();
  });

  it("benennt per Menü und Tastatur um (Enter speichert, Escape bricht ab)", async () => {
    const props = setup();
    fireEvent.click(screen.getByRole("button", { name: "Aktionen für «Kasse»" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Umbenennen" }));
    const field = screen.getByRole("textbox", { name: "Titel des Traktandums" });
    fireEvent.change(field, { target: { value: "Kasse und Budget" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(props.onRename).toHaveBeenCalledWith("e-1", "Kasse und Budget");
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Aktionen für «Kasse»" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Umbenennen" }));
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Titel des Traktandums" }), { key: "Escape" });
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(props.onRename).toHaveBeenCalledTimes(1);
  });

  it("blendet ein bzw. aus und zeigt die Hinweise", () => {
    const props = setup({ hidden: true, templateTitle: "Finanzen" });
    expect(screen.getByText("Ausgeblendet")).toBeInTheDocument();
    expect(screen.getByText("umbenannt")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Aktionen für «Kasse»" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Einblenden" }));
    expect(props.onToggleHidden).toHaveBeenCalledWith("e-1", true);
  });

  it("hat ohne Recht kein Menü", () => {
    setup({ canRename: false, canToggleHidden: false });
    expect(screen.queryByRole("button", { name: /Aktionen/ })).toBeNull();
  });
});
