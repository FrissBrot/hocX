import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentExportDialog } from "./export-dialog";

const api = vi.hoisted(() => ({
  previewDocument: vi.fn(),
  renderDocument: vi.fn(),
  exportDocumentFile: vi.fn(),
  exportPreview: vi.fn(),
  exportColumns: vi.fn(),
  saveBlob: vi.fn(),
  studioApi: { capabilities: vi.fn(), catalog: vi.fn(), brands: vi.fn(), listTemplates: vi.fn(), thumbnailUrl: vi.fn(() => "/thumb.png") },
}));
const { toast } = vi.hoisted(() => ({ toast: vi.fn() }));
const client = vi.hoisted(() => ({ browserApiFetch: vi.fn() }));

vi.mock("@/lib/documents/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/documents/api")>()), ...api }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/lib/api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api/client")>()), ...client }));

const TODAY = new Date();
const iso = (offsetDays: number) => {
  const date = new Date(TODAY.getFullYear(), TODAY.getMonth(), TODAY.getDate() + offsetDays);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
};
const TODOS = [
  { id: "t1", task: "Hallenreservation bestätigen", todo_status_code: "open", resolved_due_date: iso(-4), tags: ["Vorstand"], assigned_participant_id: "p1", assigned_participant_name: "Lea Brunner", protocol_id: null },
  { id: "t2", task: "Bälle bestellen", todo_status_code: "open", resolved_due_date: iso(10), tags: ["Material"], assigned_participant_id: "p2", assigned_participant_name: "Jonas Frei", protocol_id: null },
  { id: "t3", task: "Budget erledigt", todo_status_code: "done", resolved_due_date: iso(-20), tags: [], assigned_participant_id: null, assigned_participant_name: null, protocol_id: null },
];

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
    api.exportColumns.mockResolvedValue(["Aufgabe", "Zuständig", "Fällig"]);
    api.exportPreview.mockReset();
    client.browserApiFetch.mockReset();
    client.browserApiFetch.mockResolvedValue(TODOS);
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
    expect(within(screen.getByRole("radiogroup", { name: "Vorlage" })).getAllByRole("radio")).toHaveLength(2);
    expect(screen.queryByText("Vorlage draft-only")).not.toBeInTheDocument();
  });

  it("re-renders the preview when the template or an option changes", async () => {
    render(<DocumentExportDialog open onClose={() => undefined} context={{ documentType: "todos" }} />);
    await flushPreview();
    await waitFor(() => expect(api.previewDocument).toHaveBeenCalledTimes(1));

    fireEvent.click(await screen.findByRole("radio", { name: /Vorlage a/ }));
    await flushPreview();
    await waitFor(() => expect(api.previewDocument.mock.calls.at(-1)![0].template_id).toBe("a"));

    fireEvent.click(screen.getByRole("button", { name: /Weitere Optionen/ }));
    fireEvent.click(screen.getByRole("tab", { name: "Immer" }));
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

    fireEvent.click(await screen.findByRole("button", { name: /^PDF erstellen/ }));
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

    fireEvent.click(await screen.findByRole("button", { name: /^PDF erstellen/ }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Keine Berechtigung für Finanzdaten.", "error"));
    expect(pdfWindow.close).toHaveBeenCalled();
    expect(pdfWindow.location.replace).not.toHaveBeenCalled();
  });

  it("offers the additional formats of the document type", async () => {
    const blob = new Blob(["x"]);
    api.exportDocumentFile.mockResolvedValue({ blob, filename: "pendenzen.xlsx" });
    render(<DocumentExportDialog open onClose={() => undefined} context={{ documentType: "todos" }} />);
    await flushPreview();

    const formats = screen.getByRole("radiogroup", { name: "Format" });
    expect(within(formats).getAllByRole("radio").map((item) => item.textContent)).toEqual(["PDFZum Drucken", "CSV.csv", "Excel.xlsx"]);
    fireEvent.click(within(formats).getByRole("radio", { name: /Excel/ }));
    fireEvent.click(await screen.findByRole("button", { name: /^Excel herunterladen/ }));
    await waitFor(() => expect(api.saveBlob).toHaveBeenCalledWith(blob, "pendenzen.xlsx"));
    expect(api.exportDocumentFile.mock.calls[0][1]).toBe("xlsx");
  });

  it("blocks the export when no published template exists", async () => {
    api.studioApi.listTemplates.mockResolvedValue([template("draft-only", { published_revision: null })]);
    render(<DocumentExportDialog open onClose={() => undefined} context={{ documentType: "todos" }} />);
    expect(await screen.findByText("Für dieses Dokument ist keine veröffentlichte Vorlage verfügbar.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^PDF erstellen/ })).toBeDisabled();
    await flushPreview();
    expect(api.previewDocument).not.toHaveBeenCalled();
  });

  it("filters todos by status, overdue, tag and hand-picked selection", async () => {
    render(<DocumentExportDialog open onClose={() => undefined} context={{ documentType: "todos" }} />);
    await flushPreview();
    // Standard: offene Pendenzen, beide offenen sind ausgewählt
    expect(await screen.findByText("2 von 2 ausgewählt")).toBeInTheDocument();
    // Zähler je Chip: Erledigt 1, Überfällig 1 (nur offene)
    const group = (name: string) => within(screen.getByRole("group", { name }));
    expect(group("Status").getByRole("tab", { name: /Erledigt/ })).toHaveTextContent("Erledigt1");
    expect(group("Fälligkeit").getByRole("tab", { name: /Überfällig/ })).toHaveTextContent("Überfällig1");
    expect(screen.getByRole("button", { name: "PDF erstellen (2)" })).toBeEnabled();

    fireEvent.click(group("Fälligkeit").getByRole("tab", { name: /Überfällig/ }));
    expect(await screen.findByText("1 von 1 ausgewählt")).toBeInTheDocument();
    expect(screen.getByText(/überfällig seit/)).toBeInTheDocument();
    await flushPreview();
    await waitFor(() => expect(api.previewDocument.mock.calls.at(-1)![0].params).toMatchObject({ status: "open", overdue_only: true }));

    fireEvent.click(group("Fälligkeit").getByRole("tab", { name: /^Alle/ }));
    fireEvent.click(group("Tag").getByRole("tab", { name: /Material/ }));
    expect(await screen.findByText("1 von 1 ausgewählt")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /Bälle bestellen/ }));
    expect(screen.getByText("0 von 1 ausgewählt")).toBeInTheDocument();
    // Nichts ausgewählt: kein leerer Export
    expect(screen.getByRole("button", { name: "PDF erstellen (0)" })).toBeDisabled();
    await flushPreview();
    await waitFor(() => expect(api.previewDocument.mock.calls.at(-1)![0].params).toMatchObject({ tag: "Material", exclude_ids: ["t2"] }));

    fireEvent.click(group("Status").getByRole("tab", { name: /Erledigt/ }));
    fireEvent.click(group("Tag").getByRole("tab", { name: /Alle Tags/ }));
    expect(await screen.findByText("1 von 1 ausgewählt")).toBeInTheDocument();
    expect(screen.getByText("Budget erledigt")).toBeInTheDocument();
  });

  it("does not block the export when the todo list cannot be loaded", async () => {
    client.browserApiFetch.mockRejectedValue(new Error("offline"));
    render(<DocumentExportDialog open onClose={() => undefined} context={{ documentType: "todos" }} />);
    expect(await screen.findByText(/konnten nicht geladen werden/)).toBeInTheDocument();
    await flushPreview();
    expect(screen.getByRole("button", { name: "PDF erstellen" })).toBeEnabled();
  });

  it("previews CSV as a table and text as a WhatsApp message", async () => {
    api.exportPreview.mockImplementation((_request: unknown, format: string) =>
      Promise.resolve(
        format === "markdown"
          ? { tables: [], text: "*Offene Pendenzen*\n\n• *Bälle bestellen* — Jonas Frei" }
          : { tables: [{ title: "Pendenzen", rows: [["Aufgabe", "Zuständig"], ["Bälle bestellen", "Jonas Frei"]], total_rows: 3 }], text: null }
      )
    );
    catalog.document_types[0].formats = ["csv", "xlsx", "markdown"];
    render(<DocumentExportDialog open onClose={() => undefined} context={{ documentType: "todos" }} />);
    await flushPreview();
    const formats = await screen.findByRole("radiogroup", { name: "Format" });

    fireEvent.click(within(formats).getByRole("radio", { name: /CSV/ }));
    await flushPreview();
    expect(await screen.findByRole("cell", { name: "Bälle bestellen" })).toBeInTheDocument();
    expect(screen.getByText("… und 2 weitere Zeilen")).toBeInTheDocument();
    // Spalten erscheinen nur bei Tabellen- und Textformaten; abwählen geht an die Vorschau
    fireEvent.click(await screen.findByRole("button", { name: "Fällig", pressed: true }));
    await flushPreview();
    await waitFor(() => expect(api.exportPreview.mock.calls.at(-1)![2]).toEqual(["Fällig"]));

    fireEvent.click(within(formats).getByRole("radio", { name: /Text/ }));
    await flushPreview();
    expect(await screen.findByText("So erscheint der Text in WhatsApp")).toBeInTheDocument();
    expect(screen.getByText("Bälle bestellen", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Text kopieren/ })).toBeInTheDocument();
    catalog.document_types[0].formats = ["csv", "xlsx"];
  });
});
