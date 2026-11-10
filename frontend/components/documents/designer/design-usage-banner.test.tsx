import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { DocumentTemplateInfo } from "@/lib/documents/api";

import { DesignUsageBanner } from "./design-usage-banner";

function template(usedIn: { id: string; name: string }[]): DocumentTemplateInfo {
  return {
    id: "tpl-1",
    name: "Standard",
    description: null,
    document_type: "protocol",
    variant: null,
    category: "session",
    origin: "tenant",
    system_key: null,
    source_system_key: null,
    status: "active",
    editable: true,
    is_default: false,
    brand_id: null,
    published_revision: null,
    draft_revision: null,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    used_in: usedIn,
  };
}

const two = [
  { id: "a", name: "Hock" },
  { id: "b", name: "Vorstand" },
];

describe("DesignUsageBanner", () => {
  beforeEach(() => window.localStorage.clear());

  it("lässt sich wegklicken und bleibt für dieselbe Verwendung ausgeblendet", () => {
    const { unmount } = render(<DesignUsageBanner template={template(two)} embedded={false} />);
    expect(screen.getByRole("note")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hinweis ausblenden" }));
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    unmount();

    render(<DesignUsageBanner template={template(two)} embedded={false} />);
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("erscheint wieder, sobald sich die Verwendung ändert", () => {
    const { unmount } = render(<DesignUsageBanner template={template(two)} embedded={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Hinweis ausblenden" }));
    unmount();

    render(<DesignUsageBanner template={template([...two, { id: "c", name: "GV" }])} embedded={false} />);
    expect(screen.getByRole("note")).toBeInTheDocument();
  });
});
