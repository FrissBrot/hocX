import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => <a href={href} {...props}>{children}</a>,
}));

import { RouteTabs } from "./route-tabs";

const TABS = [
  { href: "/a", label: "Übersicht" },
  { href: "/b", label: "Anmeldeereignisse" },
  { href: "/c", label: "Sperren" },
];

describe("RouteTabs", () => {
  it("markiert den aktiven Reiter und lässt nur ihn im Tab-Fluss", () => {
    render(<RouteTabs tabs={TABS} activeHref="/b" />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveAttribute("aria-current", "page");
    expect(tabs.map((tab) => tab.tabIndex)).toEqual([-1, 0, -1]);
    expect(screen.getByRole("tablist")).toHaveClass("route-tabs");
  });

  it("Pfeiltasten verschieben den Fokus (manuelle Aktivierung)", () => {
    render(<RouteTabs tabs={TABS} activeHref="/a" />);
    const tabs = screen.getAllByRole("tab");
    tabs[0].focus();
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(document.activeElement).toBe(tabs[1]);
    fireEvent.keyDown(tabs[1], { key: "End" });
    expect(document.activeElement).toBe(tabs[2]);
  });

  it("rendert mit weniger als zwei Reitern nichts", () => {
    const { container } = render(<RouteTabs tabs={[TABS[0]]} activeHref="/a" />);
    expect(container).toBeEmptyDOMElement();
  });
});
