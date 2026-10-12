import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProtocolElement, ProtocolElementBlock } from "@/types/api";
import { ProtocolSearchModal } from "./protocol-search";

const elements = [
  { id: "blauring", section_name_snapshot: "Zusammenarbeit Blauring", blocks: [
    { id: "text", element_type_code: "text", text_content: "Lagerleitung SoLa 28" } as ProtocolElementBlock,
  ] },
  { id: "sola", section_name_snapshot: "SOLA 2026", blocks: [] },
  { id: "notes", section_name_snapshot: "Sitzungsnotizen", blocks: [
    { id: "notes-text", element_type_code: "text", text_content: "SOLA 2026" } as ProtocolElementBlock,
  ] },
  { id: "sola-next", section_name_snapshot: "SOLA 2027", blocks: [] },
] as ProtocolElement[];

describe("ProtocolSearchModal", () => {
  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  });

  it("zeigt Titeltreffer zuerst und springt mit Enter zum ersten Titeltreffer", () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    render(<ProtocolSearchModal open onClose={onClose} onSelect={onSelect}
      elements={elements} todosByBlock={{}} textDrafts={{}} protocolNumber="1" />);

    const input = screen.getByRole("textbox");
    expect(screen.getAllByRole("option").map((option) => option.querySelector(".protocol-search-item-index")?.textContent))
      .toEqual(["1", "2", "3", "4"]);

    fireEvent.change(input, { target: { value: "sola" } });
    const options = screen.getAllByRole("option");
    expect(options.map((option) => option.querySelector(".protocol-search-item-title")?.textContent))
      .toEqual(["SOLA 2026", "SOLA 2027", "Zusammenarbeit Blauring", "Sitzungsnotizen"]);
    expect(options.map((option) => option.querySelector(".protocol-search-item-index")?.textContent))
      .toEqual(["2", "4", "1", "3"]);
    expect(options[0]).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("sola");
    expect(onClose).toHaveBeenCalledOnce();

    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getAllByRole("option").map((option) => option.querySelector(".protocol-search-item-index")?.textContent))
      .toEqual(["1", "2", "3", "4"]);
  });
});
