import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/ui/rich-text-editor-lazy", () => ({
  LazyRichTextEditor: ({ value, ariaLabel }: { value: string; ariaLabel?: string }) => <div role="textbox" aria-label={ariaLabel}>{value}</div>,
}));

import { ProtocolTextBlock } from "./protocol-text-block";
import { createTextDraftStore } from "./text-drafts";

describe("ProtocolTextBlock (L4/T3)", () => {
  it("zeigt ohne Aktivierung nur die statische Darstellung, aktiv den Editor", () => {
    const store = createTextDraftStore({ b1: "**Hallo** Verein" });
    const props = { blockId: "b1", store, serverText: "", label: "Text", onChange: vi.fn(), onAcceptTrackedChanges: vi.fn() };
    const { rerender, container } = render(<ProtocolTextBlock {...props} editing={false} />);
    expect(container.querySelector("strong")?.textContent).toBe("Hallo");
    expect(screen.queryByRole("textbox")).toBeNull();
    rerender(<ProtocolTextBlock {...props} editing />);
    expect(screen.getByRole("textbox", { name: "Text" })).toHaveTextContent("**Hallo** Verein");
  });

  it("folgt dem Entwurfs-Store, ohne dass der Elternteil neu rendert", () => {
    const store = createTextDraftStore({});
    render(<ProtocolTextBlock blockId="b2" store={store} serverText="vom Server" label="Text" editing={false} onChange={vi.fn()} onAcceptTrackedChanges={vi.fn()} />);
    expect(screen.getByText("vom Server")).toBeInTheDocument();
    act(() => store.set("b2", "neu getippt"));
    expect(screen.getByText("neu getippt")).toBeInTheDocument();
  });

  it("zeigt nachverfolgte Änderungen auch statisch als Wortvergleich", () => {
    const store = createTextDraftStore({ b3: "Beginn 19:05 Uhr" });
    const { container } = render(
      <ProtocolTextBlock blockId="b3" store={store} serverText="" label="Text" editing={false} trackedBaseline="Beginn 19:00 Uhr" onChange={vi.fn()} onAcceptTrackedChanges={vi.fn()} />
    );
    expect(container.querySelector(".tracked-strike")?.textContent).toContain("19:00");
    expect(container.querySelector(".tracked-underline")?.textContent).toContain("19:05");
  });
});
