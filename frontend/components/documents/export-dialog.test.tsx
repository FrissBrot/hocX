import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentExportDialog } from "./export-dialog";

const api = vi.hoisted(() => ({
  fetchCatalog: vi.fn(),
  listStyles: vi.fn(),
  listRecipes: vi.fn(),
  previewDocument: vi.fn(),
  renderDocument: vi.fn(),
  exportDocumentFile: vi.fn(),
  saveBlob: vi.fn(),
  fetchSourceOptions: vi.fn(),
}));
const { apiFetch, toast, confirm } = vi.hoisted(() => ({ apiFetch: vi.fn(), toast: vi.fn(), confirm: vi.fn() }));

vi.mock("@/lib/documents/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/documents/api")>()), ...api }));
vi.mock("@/lib/api/client", () => ({ browserApiFetch: apiFetch, browserApiBaseUrl: "" }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirm }));

const catalog = {
  blocks: [
    { type: "todo_table", group: "tasks", access: "reader", params_schema: { properties: { status: { enum: ["all", "open", "done"], default: "open", type: "string" }, tag: { anyOf: [{ type: "string" }, { type: "null" }], default: null } } } },
    { type: "heading", group: "structure", access: "reader", params_schema: { properties: { text: { type: "string", default: "" } } } },
  ],
  document_types: [
    { key: "todos", needs_protocol: false, blocks: [{ type: "todo_table", params: { status: "open" } }] },
    { key: "protocol", needs_protocol: true, blocks: [{ type: "protocol_element", params: {} }] },
    { key: "custom", needs_protocol: false, blocks: [] },
  ],
  style_keys: ["modern", "classic", "compact"],
  languages: ["de", "en", "fr", "it"],
};

describe("DocumentExportDialog", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    Object.values(api).forEach((fn) => fn.mockReset());
    api.fetchCatalog.mockResolvedValue(catalog);
    api.listStyles.mockResolvedValue([{ id: "s1", name: "Hausstil", style_key: "modern", tokens: {}, is_default: true, version: 1, updated_at: "" }]);
    api.listRecipes.mockResolvedValue([]);
    api.previewDocument.mockResolvedValue({ pages: ["data:image/png;base64,AAA"] });
  });

  it("prefills the document type with page filters and shows the preview", async () => {
    render(<DocumentExportDialog open onClose={() => undefined} context={{ documentType: "todos", params: { status: "all", tag: "Vorstand", unknown: 1 } }} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    await waitFor(() => expect(api.previewDocument).toHaveBeenCalled());
    const request = api.previewDocument.mock.calls.at(-1)[0];
    expect(request.document_type).toBe("todos");
    expect(request.blocks).toEqual([{ type: "todo_table", params: { status: "all", tag: "Vorstand" } }]);
    expect(await screen.findByAltText("Seite 1")).toBeInTheDocument();
    // Dokumenttypen mit Protokollpflicht erscheinen ohne Protokoll nicht
    expect(screen.queryByRole("option", { name: "Protokoll" })).not.toBeInTheDocument();
  });

  it("removes blocks and renders the PDF with the composed request", async () => {
    api.renderDocument.mockResolvedValue({ content_url: "/api/stored-files/x/content", version_label: null });
    const opened = { opener: {}, closed: false, location: { replace: vi.fn() }, close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(opened as unknown as Window);
    render(<DocumentExportDialog open onClose={() => undefined} context={{ documentType: "todos" }} />);
    await screen.findByText("Todos");
    fireEvent.click(screen.getByRole("button", { name: "Block entfernen" }));
    expect(screen.getByText("Noch keine Blöcke. Füge unten einen hinzu.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "PDF erstellen" }));
    await waitFor(() => expect(api.renderDocument).toHaveBeenCalled());
    expect(api.renderDocument.mock.calls[0][0].blocks).toEqual([]);
    await waitFor(() => expect(opened.location.replace).toHaveBeenCalledWith("/api/stored-files/x/content"));
  });

  it("saves the composition as a recipe", async () => {
    apiFetch.mockResolvedValue({ id: "r1", name: "Monatsliste", document_type: "todos", blocks: [], options: {}, style_id: null, language: null, updated_at: "" });
    render(<DocumentExportDialog open onClose={() => undefined} context={{ documentType: "todos" }} />);
    await screen.findByText("Todos");
    fireEvent.change(screen.getByLabelText("Name des Rezepts"), { target: { value: "Monatsliste" } });
    fireEvent.click(screen.getByRole("button", { name: "Als neues Rezept speichern" }));
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith("/api/document-recipes", expect.objectContaining({ method: "POST" })));
    const body = JSON.parse(apiFetch.mock.calls[0][1].body);
    expect(body).toMatchObject({ name: "Monatsliste", document_type: "todos", blocks: [{ type: "todo_table" }] });
  });
});
