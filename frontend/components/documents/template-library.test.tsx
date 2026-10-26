import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import studio from "@/lib/documents/test/studio-catalog.generated.json";

import { TemplateLibrary } from "./template-library";

const api = vi.hoisted(() => ({
  studioApi: {
    listTemplates: vi.fn(),
    catalog: vi.fn(),
    duplicateTemplate: vi.fn(),
    setAssignment: vi.fn(),
    deleteTemplate: vi.fn(),
    archive: vi.fn(),
    thumbnailUrl: vi.fn(() => "/thumb.png"),
    listExamples: vi.fn(),
    importExample: vi.fn(),
    exampleThumbnailUrl: vi.fn(() => "/example.png"),
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

describe("TemplateLibrary", () => {
  beforeEach(() => {
    [toast, confirm, push, ...Object.values(api.studioApi)].forEach((fn) => fn.mockReset());
    api.studioApi.thumbnailUrl.mockReturnValue("/thumb.png");
    api.studioApi.catalog.mockResolvedValue(studio.catalog);
    api.studioApi.listTemplates.mockResolvedValue([
      template("sys-todos", { name: "todos_standard", origin: "system", system_key: "todos_standard", editable: false, is_default: true }),
      template("Vereinsliste", { document_type: "members", category: "people" }),
      template("Pendenzen Vorstand", { draft_revision: { ...published, status: "draft" } }),
    ]);
  });

  it("groups templates by document type and translates system templates", async () => {
    render(<TemplateLibrary capabilities={capabilities} />);
    const todos = await screen.findByRole("region", { name: "Pendenzenliste" });
    expect(within(todos).getByRole("heading", { name: "Pendenzenliste", level: 3 })).toBeInTheDocument();
    expect(within(todos).getByText("Offene Pendenzen als Tabelle.")).toBeInTheDocument();
    expect(within(todos).getByText("Pendenzen Vorstand")).toBeInTheDocument();
    expect(within(todos).getByText("Entwurf")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Mitgliederliste" })).toBeInTheDocument();
  });

  it("filters by search text and category", async () => {
    render(<TemplateLibrary capabilities={capabilities} />);
    await screen.findByText("Vereinsliste");
    fireEvent.change(screen.getByPlaceholderText("Vorlagen durchsuchen"), { target: { value: "vorstand" } });
    expect(screen.queryByText("Vereinsliste")).not.toBeInTheDocument();
    expect(screen.getByText("Pendenzen Vorstand")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Vorlagen durchsuchen"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("tab", { name: "Personen" }));
    expect(screen.getByText("Vereinsliste")).toBeInTheDocument();
    expect(screen.queryByText("Pendenzen Vorstand")).not.toBeInTheDocument();
  });

  it("customizes a system template as an editable copy", async () => {
    api.studioApi.duplicateTemplate.mockResolvedValue({ id: "copy-1" });
    render(<TemplateLibrary capabilities={capabilities} />);
    fireEvent.click(await screen.findByRole("button", { name: "Aktionen für «Pendenzenliste»" }));
    expect(screen.queryByRole("menuitem", { name: "Löschen" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: "Anpassen (Kopie erstellen)" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/documents/templates/copy-1"));
    expect(api.studioApi.duplicateTemplate.mock.calls[0][0]).toBe("sys-todos");
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
    render(<TemplateLibrary capabilities={{ ...capabilities, edit_templates: false, publish_templates: false }} />);
    expect(screen.queryByRole("button", { name: "Neue Vorlage" })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Aktionen für «Pendenzenliste»" }));
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["Vorschau"]);
  });
  it("offers the design examples only to admins, with the shared meeting document designs", async () => {
    api.studioApi.listExamples.mockResolvedValue([{ key: "protocol_tech", document_type: "protocol" }]);
    api.studioApi.importExample.mockResolvedValue({ id: "new-template" });
    const { unmount } = render(<TemplateLibrary capabilities={{ ...capabilities, manage_brand: false }} />);
    await screen.findByText("Vereinsliste");
    expect(screen.queryByRole("button", { name: "Beispiele" })).not.toBeInTheDocument();
    unmount();

    render(<TemplateLibrary capabilities={capabilities} scope="session" />);
    fireEvent.click(await screen.findByRole("button", { name: "Beispiele" }));
    fireEvent.click(await screen.findByRole("button", { name: "Hinzufügen" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/documents/templates/new-template"));
  });
});
