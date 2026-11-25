import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

import type { CloudNode } from "@/lib/files/file-import";

import { ImportCloudTree } from "./import-cloud-tree";

function node(ref: string, name: string, extra: Partial<CloudNode> = {}): CloudNode {
  return {
    ref, name, kind: "folder", size: null, modified_at: null, child_count: null, available: true, requires_tier: null,
    selectable: true, label_key: null, file_kind: null, ...extra,
  };
}

describe("ImportCloudTree", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
  });

  it("lädt Ebenen nach, wählt und sperrt Kinder eines gewählten Ordners", async () => {
    browserApiFetchMock.mockImplementation(async (raw: unknown) => {
      const path = String(raw);
      if (path.endsWith("/browse")) return { nodes: [node("me", "OneDrive"), node("shared", "Geteilt", { selectable: false, available: false, requires_tier: "extended" })], cursor: null };
      if (path.includes("ref=me") && path.includes("cursor=")) return { nodes: [node("item:d:2", "b.jpg", { kind: "file", size: 10, file_kind: "image" })], cursor: null };
      if (path.includes("ref=me")) return { nodes: [node("item:d:1", "Fotos")], cursor: "next-page" };
      throw new Error(path);
    });
    const selected = new Map<string, CloudNode>();
    const onToggle = vi.fn((item: CloudNode, checked: boolean) => (checked ? selected.set(item.ref, item) : selected.delete(item.ref)));
    const onRequestTier = vi.fn();
    const view = render(<ImportCloudTree jobId="j1" selected={selected} onToggle={onToggle} onRequestTier={onRequestTier} />);

    const expand = await screen.findByRole("button", { name: "OneDrive aufklappen" });
    fireEvent.click(expand);
    expect(expand).toHaveAttribute("aria-expanded", "true");
    await screen.findByText("Fotos");
    fireEvent.click(screen.getByRole("button", { name: "Weitere laden" }));
    await screen.findByText("b.jpg");
    expect(browserApiFetchMock).toHaveBeenCalledWith("/api/cloud-import/jobs/j1/browse?ref=me&cursor=next-page");

    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    expect(onToggle).toHaveBeenCalledWith(expect.objectContaining({ ref: "me" }), true);
    view.rerender(<ImportCloudTree jobId="j1" selected={new Map(selected)} onToggle={onToggle} onRequestTier={onRequestTier} />);
    await waitFor(() => expect(screen.getAllByRole("checkbox").slice(1).every((item) => (item as HTMLInputElement).disabled)).toBe(true));

    // Sammelknoten ohne Zugriff: keine Checkbox, aber «Zugriff erlauben»
    fireEvent.click(screen.getByRole("button", { name: "Zugriff erlauben" }));
    expect(onRequestTier).toHaveBeenCalledWith("extended");
  });
});
