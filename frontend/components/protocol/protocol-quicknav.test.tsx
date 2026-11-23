import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { ProtocolQuickNav, type QuickNavItem } from "./protocol-quicknav";

const items: QuickNavItem[] = [
  { id: "e1", name: "Begrüssung", icon: "protocols" as QuickNavItem["icon"] },
  { id: "e2", name: "Finanzen", icon: "protocols" as QuickNavItem["icon"] },
];

it("springt per Klick zum Punkt und verschiebt per Alt+Pfeil", async () => {
  const onSelect = vi.fn();
  const onReorder = vi.fn().mockResolvedValue(undefined);
  render(<ProtocolQuickNav items={items} selectedId="e2" readOnly={false} onSelect={onSelect} onReorder={onReorder} />);

  const first = screen.getByRole("button", { name: "Begrüssung" });
  fireEvent.click(first);
  expect(onSelect).toHaveBeenCalledWith("e1");
  expect(screen.getByRole("button", { name: "Finanzen" }).className).toContain("protocol-quicknav-item-active");

  fireEvent.keyDown(first, { key: "ArrowDown", altKey: true });
  await vi.waitFor(() => expect(onReorder).toHaveBeenCalledWith("e1", "e2"));
});

it("ohne Schreibrecht weder ziehbar noch per Tastatur verschiebbar", () => {
  const onReorder = vi.fn();
  const { container } = render(<ProtocolQuickNav items={items} selectedId={null} readOnly onSelect={vi.fn()} onReorder={onReorder} />);
  expect(container.querySelector("[draggable='true']")).toBeNull();
  fireEvent.keyDown(screen.getByRole("button", { name: "Begrüssung" }), { key: "ArrowDown", altKey: true });
  expect(onReorder).not.toHaveBeenCalled();
});
