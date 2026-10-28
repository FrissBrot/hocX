import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import studio from "@/lib/documents/test/studio-catalog.generated.json";

import { TemplateLibrary } from "./template-library";

const api = vi.hoisted(() => ({
  studioApi: {
    listTemplates: vi.fn(),
    catalog: vi.fn(),
    brands: vi.fn(),
    duplicateTemplate: vi.fn(),
    createTemplate: vi.fn(),
    updateTemplate: vi.fn(),
    setAssignment: vi.fn(),
    deleteTemplate: vi.fn(),
    archive: vi.fn(),
    archiveUnused: vi.fn(),
    thumbnailUrl: vi.fn(() => "/thumb.png"),
    listExamples: vi.fn(),
    importExample: vi.fn(),
    exampleThumbnailUrl: vi.fn(() => "/example.png"),
    exampleBrandThumbnailUrl: vi.fn(() => "/example-brand.png"),
  },
}));
const { toast, confirm, push } = vi.hoisted(() => ({ toast: vi.fn(), confirm: vi.fn(), push: vi.fn() }));

vi.mock("@/lib/documents/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/documents/api")>()), ...api }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirm }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const published = { id: "rev", revision_no: 1, status: "published", lock_version: 1, brand_mode: "follow", schema_version: 1, note: null, created_at: "", updated_at: "", published_at: "", created_by_name: null, template_id: null, brand_id: null };

function template(id: string, overrides: Record<string, unknown> = {}) {
  return { id, name: id, description: null, document_type: "todos", variant: null, category: "tasks", origin: "tenant", system_key: null, source_system_key: null, status: "active", editable: true, is_default: false, brand_id: null, published_revision: published, draft_revision: null, created_at: "", updated_at: "", ...overrides };
}

const capabilities = { export: true, view_templates: true, edit_templates: true, publish_templates: true, manage_brand: true, finance_data: true, personal_data: true };
const brands = [{ id: "b1", name: "Verein", is_default: true, archived: false, revision: 2 }, { id: "b2", name: "Jubiläum", is_default: false, archived: false, revision: 1 }];

describe("TemplateLibrary", () => {
  beforeEach(() => {
    [toast, confirm, push, ...Object.values(api.studioApi)].forEach((fn) => fn.mockReset());
    api.studioApi.thumbnailUrl.mockReturnValue("/thumb.png");
    api.studioApi.exampleBrandThumbnailUrl.mockReturnValue("/example-brand.png");
    api.studioApi.catalog.mockResolvedValue(studio.catalog);
    api.studioApi.brands.mockResolvedValue(brands);
    api.studioApi.listExamples.mockResolvedValue([{ key: "fokus", document_type: "protocol" }]);
    api.studioApi.listTemplates.mockResolvedValue([
      template("sys-todos", { name: "todos_standard", origin: "system", system_key: "todos_standard", editable: false, is_default: true }),
      template("sys-protocol", { name: "protocol_standard", document_type: "protocol", category: "protocols", origin: "system", system_key: "protocol_standard", editable: false, is_default: true }),
      template("Vereinsliste", { document_type: "members", category: "people", export_count: 4 }),
      template("Pendenzen Vorstand", { origin: "copy", source_system_key: "todos_standard", draft_revision: { ...published, status: "draft" }, update_revision_no: 3 }),
      template("Hock", { document_type: "protocol", category: "protocols", catalog_key: "fokus", used_in: [{ id: "s1", name: "Vorstand" }, { id: "s2", name: "Jahresversammlung" }] }),
    ]);
  });

  it("lists only the club's own templates, grouped into meeting and other documents", async () => {
    render(<TemplateLibrary capabilities={capabilities} />);
    const session = await screen.findByRole("region", { name: "Sitzung" });
    expect(within(session).getByText("Hock")).toBeInTheDocument();
    expect(within(session).getByText("Protokoll · 2 Protokollvorlagen")).toBeInTheDocument();
    expect(within(session).getByText("Aus Katalog · Fokus")).toBeInTheDocument();
    const other = screen.getByRole("region", { name: "Weitere Dokumente" });
    expect(within(other).getByText("Vereinsliste")).toBeInTheDocument();
    expect(within(other).getByText("Mitgliederliste · 4 Exporte")).toBeInTheDocument();
    expect(within(other).getByText("Aus Katalog · Pendenzenliste")).toBeInTheDocument();
    expect(within(other).getByText("Update v3")).toBeInTheDocument();
    expect(within(other).getByText("Entwurf")).toBeInTheDocument();
    // Mitgelieferte Vorlagen stehen nur im Katalog
    expect(screen.queryByRole("heading", { name: "Pendenzenliste", level: 3 })).not.toBeInTheDocument();
    // Lücke: Einladung und Traktandenliste fehlen, der Export nutzt dann den Katalog-Standard
    expect(within(session).getByRole("button", { name: /Aus Katalog hinzufügen/ })).toBeInTheDocument();
  });

  it("filters by search text", async () => {
    render(<TemplateLibrary capabilities={capabilities} />);
    await screen.findByText("Vereinsliste");
    fireEvent.change(screen.getByPlaceholderText("Vorlagen durchsuchen"), { target: { value: "vorstand" } });
    expect(screen.queryByText("Vereinsliste")).not.toBeInTheDocument();
    expect(screen.getByText("Pendenzen Vorstand")).toBeInTheDocument();
  });

  it("adds exactly one template from the catalogue", async () => {
    api.studioApi.duplicateTemplate.mockResolvedValue({ id: "copy-1" });
    render(<TemplateLibrary capabilities={capabilities} />);
    fireEvent.click(await screen.findByRole("button", { name: "Katalog durchsuchen" }));
    const dialog = await screen.findByRole("dialog", { name: "Katalog" });
    fireEvent.click(within(dialog).getByRole("button", { name: /^Pendenzenliste/ }));
    // Schon übernommen (Kopie vorhanden): bewusst nochmals hinzufügen
    fireEvent.click(within(dialog).getByRole("button", { name: "«Pendenzenliste» hinzufügen" }));
    await waitFor(() => expect(api.studioApi.duplicateTemplate).toHaveBeenCalledWith("sys-todos", "Pendenzenliste"));
    expect(toast).toHaveBeenCalledWith("«Pendenzenliste» übernommen – nur diese eine Vorlage", "success");
  });

  it("creates a template from a catalogue design with the club brand", async () => {
    api.studioApi.importExample.mockResolvedValue({ id: "new-template" });
    api.studioApi.updateTemplate.mockResolvedValue({});
    render(<TemplateLibrary capabilities={capabilities} />);
    fireEvent.click(await screen.findByRole("button", { name: "Neue Vorlage" }));
    const dialog = await screen.findByRole("dialog", { name: "Neue Vorlage" });
    fireEvent.click(within(dialog).getByRole("radio", { name: /Protokoll Fokus/ }));
    expect(within(dialog).getByRole("textbox", { name: "Name" })).toHaveValue("Protokoll Fokus");
    fireEvent.click(within(dialog).getByRole("button", { name: "Erstellen und gestalten" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/documents/templates/new-template"));
    expect(api.studioApi.importExample).toHaveBeenCalledWith("fokus", "Protokoll Fokus");
    // Standard-Erscheinungsbild: kein eigenes Profil, keine Zuweisung nötig
    expect(api.studioApi.updateTemplate).not.toHaveBeenCalled();
  });

  it("creates a blank template with another brand profile", async () => {
    api.studioApi.createTemplate.mockResolvedValue({ id: "blank-1" });
    api.studioApi.updateTemplate.mockResolvedValue({});
    render(<TemplateLibrary capabilities={capabilities} />);
    fireEvent.click(await screen.findByRole("button", { name: "Neue Vorlage" }));
    const dialog = await screen.findByRole("dialog", { name: "Neue Vorlage" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Mitgliederliste" }));
    fireEvent.click(within(dialog).getByRole("radio", { name: /^Leer/ }));
    fireEvent.change(within(dialog).getByLabelText("Erscheinungsbild"), { target: { value: "b2" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Erstellen und gestalten" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/documents/templates/blank-1"));
    expect(api.studioApi.createTemplate).toHaveBeenCalledWith({ name: "Mitgliederliste", document_type: "members", from_template_id: null });
    expect(api.studioApi.updateTemplate).toHaveBeenCalledWith("blank-1", { brand_id: "b2" });
  });

  it("archives unused templates from the cleanup hint", async () => {
    api.studioApi.listTemplates.mockResolvedValue([template("Alt A", { cleanup_candidate: true }), template("Alt B", { cleanup_candidate: true }), template("Aktiv")]);
    api.studioApi.archiveUnused.mockResolvedValue({ archived: 1 });
    render(<TemplateLibrary capabilities={capabilities} />);
    expect(await screen.findByText("2 Vorlagen werden nicht verwendet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Aufräumen" }));
    const dialog = await screen.findByRole("dialog", { name: "Nicht verwendete Vorlagen archivieren" });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Alt B/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "1 archivieren" }));
    await waitFor(() => expect(api.studioApi.archiveUnused).toHaveBeenCalledWith(["Alt A"]));
    expect(toast).toHaveBeenCalledWith("1 Vorlage archiviert", "success");
  });

  it("sets the default template through an assignment", async () => {
    api.studioApi.setAssignment.mockResolvedValue(null);
    render(<TemplateLibrary capabilities={capabilities} />);
    fireEvent.click(await screen.findByRole("button", { name: "Aktionen für «Pendenzen Vorstand»" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Als Standard festlegen" }));
    await waitFor(() => expect(api.studioApi.setAssignment).toHaveBeenCalledWith({ document_type: "todos", template_id: "Pendenzen Vorstand" }));
    expect(toast).toHaveBeenCalledWith("Standardvorlage festgelegt.", "success");
  });

  it("deletes only after a danger confirmation", async () => {
    confirm.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    api.studioApi.deleteTemplate.mockResolvedValue(null);
    render(<TemplateLibrary capabilities={capabilities} />);
    const openMenu = async () => fireEvent.click(await screen.findByRole("button", { name: "Aktionen für «Vereinsliste»" }));
    await openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: "Löschen" }));
    await waitFor(() => expect(confirm).toHaveBeenCalledWith(expect.objectContaining({ tone: "danger" })));
    expect(api.studioApi.deleteTemplate).not.toHaveBeenCalled();
    await openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: "Löschen" }));
    await waitFor(() => expect(api.studioApi.deleteTemplate).toHaveBeenCalledWith("Vereinsliste"));
  });

  it("hides editing actions for readers", async () => {
    api.studioApi.listTemplates.mockResolvedValue([template("Vereinsliste", { document_type: "members", category: "people", editable: false })]);
    render(<TemplateLibrary capabilities={{ ...capabilities, edit_templates: false, publish_templates: false }} />);
    expect(screen.queryByRole("button", { name: "Neue Vorlage" })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Aktionen für «Vereinsliste»" }));
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["Vorschau"]);
  });
});
