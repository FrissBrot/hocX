import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OutlineAddItem, ProtocolOutline } from "./protocol-outline";

const items = [
  { id: "a", title: "Begrüssung", summary: "12/15 anwesend" },
  { id: "b", title: "Kasse", summary: "Text" },
  { id: "c", title: "Varia", summary: "", hidden: true },
];

describe("ProtocolOutline", () => {
  it("zeigt Nummer, Titel, Zusammenfassung und markiert den aktiven Punkt", () => {
    const onSelect = vi.fn();
    render(<ProtocolOutline items={items} selectedId="b" canReorder={false} onSelect={onSelect} onReorder={vi.fn()} />);
    const nav = screen.getByRole("navigation", { name: "Gliederung des Protokolls" });
    expect(nav).toHaveTextContent("12/15 anwesend");
    expect(nav).toHaveTextContent("Ausgeblendet");
    const kasse = screen.getByRole("button", { name: /Kasse/ });
    expect(kasse).toHaveAttribute("aria-current", "location");
    fireEvent.click(screen.getByRole("button", { name: /Begrüssung/ }));
    expect(onSelect).toHaveBeenCalledWith("a");
    expect(screen.queryByRole("button", { name: /nach oben/ })).toBeNull();
  });

  it("verschiebt per Alt+Pfeil hinter bzw. vor den Nachbarn", () => {
    const onReorder = vi.fn();
    render(<ProtocolOutline items={items} selectedId={null} canReorder onSelect={vi.fn()} onReorder={onReorder} />);
    const kasse = screen.getAllByRole("button").find((button) => button.classList.contains("protocol-outline-item") && button.textContent?.includes("Kasse"))!;
    fireEvent.keyDown(kasse, { key: "ArrowDown", altKey: true });
    expect(onReorder).toHaveBeenLastCalledWith("b", "c", "after");
    fireEvent.keyDown(kasse, { key: "ArrowUp", altKey: true });
    expect(onReorder).toHaveBeenLastCalledWith("b", "a", "before");
  });
});

describe("OutlineAddItem", () => {
  it("fügt mit Enter hinzu und leert danach das Feld", async () => {
    const onAdd = vi.fn().mockResolvedValue(true);
    render(<OutlineAddItem onAdd={onAdd} />);
    const field = screen.getByRole("textbox", { name: "Traktandum hinzufügen" });
    fireEvent.change(field, { target: { value: "Neues Traktandum" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(onAdd).toHaveBeenCalledWith("Neues Traktandum");
    await screen.findByDisplayValue("");
  });
});
