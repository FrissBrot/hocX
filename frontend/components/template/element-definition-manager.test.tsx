import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ElementDefinition } from "@/types/api";

const api = vi.fn();
const toast = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (...args: unknown[]) => api(...args), browserApiBaseUrl: "" }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn() }));
vi.mock("@/lib/hooks/use-tag-config", () => ({ useTagConfig: () => ({ tagConfig: {}, updateTagColor: vi.fn(), renameTag: vi.fn() }) }));
vi.mock("@/components/ui/rich-text-editor", () => ({ RichTextEditor: () => null }));

import { ElementDefinitionManager } from "./element-definition-manager";

const original: ElementDefinition = {
  id: "original", tenant_id: "tenant", title: "Sitzungsinhalt", description: "Beschreibung",
  is_active: true, created_at: "2026-09-23", updated_at: "2026-09-23",
  blocks: [1, 2].map((id) => ({
    id, title: `Block ${id}`, description: null, block_title: "Untertitel",
    default_content: "Vorgabe", copy_from_last_protocol: true,
    element_type_id: 1, render_type_id: 2, is_editable: false,
    allows_multiple_values: false, export_visible: true, is_visible: true,
    sort_index: id * 10, render_order: null, latex_template: null,
    configuration_json: { title_as_subtitle: false, nested: { values: ["unverändert"] } },
  })),
};
const copy = { ...original, id: "copy", title: "Sitzungsinhalt (Kopie)" };

function setup() {
  render(<ElementDefinitionManager initialDefinitions={[original]} knownEventTags={[]} tenantId="tenant" />);
}

beforeEach(() => { api.mockReset(); toast.mockReset(); });

describe("Elemente duplizieren", () => {
  it("übernimmt alle Blöcke und Einstellungen und öffnet die neue Kopie", async () => {
    api.mockResolvedValueOnce(copy);
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Duplizieren" }));
    await waitFor(() => expect(screen.getByDisplayValue(copy.title)).toBeInTheDocument());
    const [path, options] = api.mock.calls[0];
    expect(path).toBe("/api/element-definitions");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({
      title: copy.title, description: original.description, is_active: true, blocks: original.blocks,
    });
    expect(screen.getByText(original.title, { selector: "strong" })).toBeInTheDocument();
    expect(original.title).toBe("Sitzungsinhalt");
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("dupliziert"), "success");
  });

  it("sperrt weitere Klicks während des Speicherns und erlaubt nach Fehlern einen neuen Versuch", async () => {
    let reject!: (error: Error) => void;
    api.mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; }));
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Duplizieren" }));
    const pending = screen.getByRole("button", { name: "Wird dupliziert…" });
    expect(pending).toBeDisabled();
    fireEvent.click(pending);
    expect(api).toHaveBeenCalledTimes(1);
    reject(new Error("Speichern fehlgeschlagen"));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Speichern fehlgeschlagen", "error"));
    expect(screen.getByRole("button", { name: "Duplizieren" })).toBeEnabled();
    expect(screen.queryByDisplayValue(copy.title)).not.toBeInTheDocument();
    api.mockResolvedValueOnce(copy);
    fireEvent.click(screen.getByRole("button", { name: "Duplizieren" }));
    await waitFor(() => expect(screen.getByDisplayValue(copy.title)).toBeInTheDocument());
  });
});
