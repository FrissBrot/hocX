import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentExportDialog } from "./export-dialog";

const api = vi.hoisted(() => ({
  previewDocument: vi.fn(),
  renderDocument: vi.fn(),
  exportDocumentFile: vi.fn(),
  saveBlob: vi.fn(),
  studioApi: { capabilities: vi.fn(), catalog: vi.fn(), brands: vi.fn(), listTemplates: vi.fn(), thumbnailUrl: vi.fn(() => "/thumb.png") },
}));
const { toast } = vi.hoisted(() => ({ toast: vi.fn() }));

vi.mock("@/lib/documents/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/documents/api")>()), ...api }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));

const revision = { id: "rev-1", revision_no: 1, status: "published", lock_version: 1, brand_mode: "follow", schema_version: 1, note: null, created_at: "", updated_at: "", published_at: "", created_by_name: null, template_id: null, brand_id: null };

function template(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    name: `Vorlage ${id}`,
    description: null,
    document_type: "todos",
    variant: null,
    category: "tasks",
    origin: "tenant",
    system_key: null,
    source_system_key: null,
    status: "active",
    editable: true,
    is_default: false,
    brand_id: null,
    published_revision: revision,
    draft_revision: null,
    created_at: "",
    updated_at: "",
    ...overrides,
  };
}

const capabilities = { export: true, view_templates: true, edit_templates: true, publish_templates: true, manage_brand: true, finance_data: true, personal_data: true };
const catalog = {
  document_types: [
    { key: "todos", category: "tasks", needs_protocol: false, formats: ["csv", "xlsx"] },
    { key: "protocol", category: "protocols", needs_protocol: true, formats: [] },
  ],
};

async function flushPreview() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(500);
  });
}

describe("DocumentExportDialog", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    toast.mockReset();
    [api.previewDocument, api.renderDocument, api.exportDocumentFile, api.saveBlob].forEach((fn) => fn.mockReset());
    api.studioApi.capabilities.mockResolvedValue(capabilities);
    api.studioApi.catalog.mockResolvedValue(catalog);
    api.studioApi.brands.mockResolvedValue([]);
    api.studioApi.listTemplates.mockResolvedValue([
      template("a"),
      template("b", { is_default: true }),
      template("draft-only", { published_revision: null }),
      template("old", { status: "archived" }),
    ]);
    api.previewDocument.mockResolvedValue({ pages: ["data:image/png;base64,AAA"], page_count: 1, diagnostics: [] });
  });

  it("preselects the default template and previews with the page filters", async () => {
    render(<DocumentExportDialog open onClose={() => undefined} context={{ documentType: "todos", params: { status: "all" } }} />);
    await flushPreview();
    await waitFor(() => expect(api.previewDocument).toHaveBeenCalled());
    const request = api.previewDocument.mock.calls.at(-1)![0];
    expect(request).toMatchObject({ document_type: "todos", template_id: "b", params: { status: "all" }, options: { watermark: "auto" } });
    expect(api.studioApi.listTemplates).toHaveBeenCalledWith({ documentType: "todos" });
    expect(await screen.findByAltText("Seite 1")).toBeInTheDocument();
    // Nur veröffentlichte, aktive Vorlagen sind wählbar
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    expect(screen.queryByText("Vorlage draft-only")).not.toBeInTheDocument();
  });

  it("re-renders the preview when the template or an option changes", async () => {
    render(<DocumentExportDialog open onClose={() => undefined} context={{ documentType: "todos" }} />);
    await flushPreview();
    await waitFor(() => expect(api.previewDocument).toHaveBeenCalledTimes(1));

    fireEvent.click(await screen.findByRole("radio", { name: /Vorlage a/ }));
    await flushPreview();
    await waitFor(() => expect(api.previewDocument.mock.calls.at(-1)![0].template_id).toBe("a"));

    fireEvent.change(screen.getByLabelText("Wasserzeichen «Entwurf»"), { target: { value: "on" } });
    await flushPreview();
    await waitFor(() => expect(api.previewDocument.mock.calls.at(-1)![0].options.watermark).toBe("on"));
  });

  it("creates the PDF in the tab opened during the click", async () => {
    const pdfWindow = { opener: {}, closed: false, location: { replace: vi.fn() }, close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(pdfWindow as unknown as Window);
    api.renderDocument.mockResolvedValue({ content_url: "/api/stored-files/x/content", version_label: "v1.0" });
    const onExported = vi.fn();
    render(<DocumentExportDialog open onClose={() => undefined} context={{ documentType: "todos" }} onExported={onExported} />);
    await flushPreview();

    fireEvent.click(await screen.findByRole("button", { name: "PDF erstellen" }));
    await waitFor(() => expect(pdfWindow.location.replace).toHaveBeenCalledWith("/api/stored-files/x/content"));
    expect(api.renderDocument.mock.calls[0][0]).toMatchObject({ document_type: "todos", template_id: "b" });
    expect(toast).toHaveBeenCalledWith("PDF erstellt (Version v1.0).", "success", expect.objectContaining({ onMessageClick: expect.any(Function) }));
    expect(onExported).toHaveBeenCalled();
  });

  it("closes the empty tab and shows the backend message when rendering fails", async () => {
    const pdfWindow = { opener: {}, closed: false, location: { replace: vi.fn() }, close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(pdfWindow as unknown as Window);
    api.renderDocument.mockRejectedValue(new Error("Keine Berechtigung für Finanzdaten."));
    render(<DocumentExportDialog open onClose={() => undefined} context={{ documentType: "todos" }} />);
    await flushPreview();

    fireEvent.click(await screen.findByRole("button", { name: "PDF erstellen" }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Keine Berechtigung für Finanzdaten.", "error"));
    expect(pdfWindow.close).toHaveBeenCalled();
    expect(pdfWindow.location.replace).not.toHaveBeenCalled();
  });

  it("offers the additional formats of the document type", async () => {
    const blob = new Blob(["x"]);
    api.exportDocumentFile.mockResolvedValue({ blob, filename: "pendenzen.xlsx" });
    render(<DocumentExportDialog open onClose={() => undefined} context={{ documentType: "todos" }} />);
    await flushPreview();

    fireEvent.click(await screen.findByRole("button", { name: "Excel" }));
    await waitFor(() => expect(api.saveBlob).toHaveBeenCalledWith(blob, "pendenzen.xlsx"));
    expect(api.exportDocumentFile.mock.calls[0][1]).toBe("xlsx");
    expect(screen.getByRole("button", { name: "CSV" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Kalender (ICS)" })).not.toBeInTheDocument();
  });

  it("blocks the export when no published template exists", async () => {
    api.studioApi.listTemplates.mockResolvedValue([template("draft-only", { published_revision: null })]);
    render(<DocumentExportDialog open onClose={() => undefined} context={{ documentType: "todos" }} />);
    expect(await screen.findByText("Für dieses Dokument ist keine veröffentlichte Vorlage verfügbar.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "PDF erstellen" })).toBeDisabled();
    await flushPreview();
    expect(api.previewDocument).not.toHaveBeenCalled();
  });
});
