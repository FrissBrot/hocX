import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import { contentFixture } from "@/lib/documents/test/content-fixture";
import studio from "@/lib/documents/test/studio-catalog.generated.json";

import { TemplateDesigner } from "./designer";

const api = vi.hoisted(() => ({
  previewDocument: vi.fn(),
  studioApi: {
    getTemplate: vi.fn(),
    catalog: vi.fn(),
    capabilities: vi.fn(),
    brands: vi.fn(),
    assets: vi.fn(),
    components: vi.fn(),
    saveDraft: vi.fn(),
    publish: vi.fn(),
    updateTemplate: vi.fn(),
    duplicateTemplate: vi.fn(),
    discardDraft: vi.fn(),
    createComponent: vi.fn(),
  },
}));
const { toast, confirm, push } = vi.hoisted(() => ({ toast: vi.fn(), confirm: vi.fn(), push: vi.fn() }));

vi.mock("@/lib/documents/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/documents/api")>()), ...api }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirm }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const revision = (overrides: Record<string, unknown> = {}) => ({ id: "rev-draft", revision_no: 2, status: "draft", lock_version: 3, brand_mode: "follow", schema_version: 1, note: null, created_at: "", updated_at: "", published_at: null, created_by_name: null, template_id: "tpl", brand_id: null, ...overrides });

function detail(overrides: Record<string, unknown> = {}) {
  return {
    id: "tpl",
    name: "Pendenzen Verein",
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
    published_revision: revision({ id: "rev-pub", revision_no: 1, status: "published", lock_version: 1 }),
    draft_revision: revision(),
    created_at: "",
    updated_at: "",
    content: contentFixture(),
    working_revision_id: "rev-draft",
    diagnostics: [],
    ...overrides,
  };
}

const capabilities = { export: true, view_templates: true, edit_templates: true, publish_templates: true, manage_brand: true, finance_data: true, personal_data: true };
const brand = { id: "brand-1", name: "Standard", description: null, is_default: true, archived: false, revision: 1, lock_version: 1, tokens: studio.brand_tokens, updated_at: "" };

async function renderDesigner() {
  render(<TemplateDesigner templateId="tpl" />);
  await screen.findByRole("textbox", { name: "Name der Vorlage" });
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function canvasNode(name: string) {
  return within(screen.getByRole("main", { name: "Arbeitsfläche" })).getByRole("button", { name });
}

describe("TemplateDesigner", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    [toast, confirm, push, api.previewDocument, ...Object.values(api.studioApi)].forEach((fn) => fn.mockReset());
    try {
      window.localStorage.clear();
    } catch {
      // ohne Speicher gilt der einfache Modus
    }
    api.studioApi.getTemplate.mockResolvedValue(detail());
    api.studioApi.catalog.mockResolvedValue(studio.catalog);
    api.studioApi.capabilities.mockResolvedValue(capabilities);
    api.studioApi.brands.mockResolvedValue([brand]);
    api.studioApi.assets.mockResolvedValue([]);
    api.studioApi.components.mockResolvedValue([]);
    api.previewDocument.mockResolvedValue({ pages: ["data:image/png;base64,AAA"], page_count: 1, diagnostics: [], template_id: null, template_source: null, design_hash: null });
    api.studioApi.saveDraft.mockImplementation(async (_id: string, body: { lock_version: number | null }) => ({ revision: revision({ lock_version: (body.lock_version ?? 3) + 1 }), diagnostics: [] }));
  });

  it("inserts a library element at the end of the body and autosaves with the lock version", async () => {
    await renderDesigner();
    const [insertText] = screen.getAllByRole("button", { name: "«Text» einfügen" });
    fireEvent.click(insertText);
    expect(screen.getByText("Ungespeicherte Änderungen")).toBeInTheDocument();

    await advance(1300);
    await waitFor(() => expect(api.studioApi.saveDraft).toHaveBeenCalledTimes(1));
    const [, body] = api.studioApi.saveDraft.mock.calls[0];
    expect(body.lock_version).toBe(3);
    expect(body.content.body.map((node: { type: string }) => node.type)).toEqual(["text", "section", "verify_note", "text"]);
    await waitFor(() => expect(screen.getByText("Gespeichert")).toBeInTheDocument());

    // Der nächste Speichervorgang verwendet die neue Sperrversion
    fireEvent.click(screen.getAllByRole("button", { name: "«Text» einfügen" })[0]);
    await advance(1300);
    await waitFor(() => expect(api.studioApi.saveDraft).toHaveBeenCalledTimes(2));
    expect(api.studioApi.saveDraft.mock.calls[1][1].lock_version).toBe(4);
  });

  // Simuliert den Server: Antwort erst auf Abruf, Sperrversion wird wie im Backend geprüft
  function controlledServer(initialLock = 3) {
    const state = { lock: initialLock, pending: [] as Array<() => void> };
    api.studioApi.saveDraft.mockImplementation(
      (_id: string, body: { lock_version: number | null }) =>
        new Promise((resolve, reject) => {
          state.pending.push(() => {
            if (body.lock_version !== null && body.lock_version !== state.lock) {
              reject(new ApiError("Konflikt", "conflict", 409, { lock_version: state.lock }));
              return;
            }
            state.lock += 1;
            resolve({ revision: revision({ lock_version: state.lock }), diagnostics: [] });
          });
        })
    );
    const respond = async () => {
      await act(async () => {
        state.pending.shift()!();
        await Promise.resolve();
      });
    };
    return { state, respond };
  }

  const insertText = () => fireEvent.click(screen.getAllByRole("button", { name: "«Text» einfügen" })[0]);
  const conflictText = "Jemand anderes hat diese Vorlage inzwischen geändert.";

  it("keeps changes made during a running save dirty and saves them with the new lock version (STUDIO-001)", async () => {
    const server = controlledServer();
    await renderDesigner();
    insertText();
    await advance(1300);
    await waitFor(() => expect(api.studioApi.saveDraft).toHaveBeenCalledTimes(1));

    // Änderung während der laufenden Anfrage
    insertText();
    await server.respond();
    expect(screen.queryByText("Gespeichert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Veröffentlichen" })).toBeDisabled();

    await advance(1300);
    await waitFor(() => expect(api.studioApi.saveDraft).toHaveBeenCalledTimes(2));
    const second = api.studioApi.saveDraft.mock.calls[1][1];
    expect(second.lock_version).toBe(4);
    expect(second.content.body).toHaveLength(5);
    await server.respond();
    expect(await screen.findByText("Gespeichert")).toBeInTheDocument();
    expect(screen.queryByText(conflictText)).not.toBeInTheDocument();
  });

  it("does not send a second save while one is pending and follows up afterwards (STUDIO-001)", async () => {
    const server = controlledServer();
    await renderDesigner();
    insertText();
    await advance(1300);
    await waitFor(() => expect(api.studioApi.saveDraft).toHaveBeenCalledTimes(1));

    // Autosave-Timer der zweiten Änderung läuft ab, während die erste Anfrage noch offen ist
    insertText();
    await advance(1300);
    expect(api.studioApi.saveDraft).toHaveBeenCalledTimes(1);

    await server.respond();
    await waitFor(() => expect(api.studioApi.saveDraft).toHaveBeenCalledTimes(2));
    expect(api.studioApi.saveDraft.mock.calls[1][1].lock_version).toBe(4);
    expect(api.studioApi.saveDraft.mock.calls[1][1].content.body).toHaveLength(5);
    await server.respond();
    expect(await screen.findByText("Gespeichert")).toBeInTheDocument();
    expect(screen.queryByText(conflictText)).not.toBeInTheDocument();
  });

  it("saves a change of the brand mode alone (STUDIO-004)", async () => {
    await renderDesigner();
    fireEvent.change(screen.getByRole("combobox", { name: "Bearbeitungsmodus" }), { target: { value: "advanced" } });
    const brandMode = screen.getAllByRole("combobox", { hidden: true }).find((element) => within(element).queryByRole("option", { name: "Mitgehen", hidden: true }));
    fireEvent.change(brandMode!, { target: { value: "pinned" } });
    expect(screen.getByText("Ungespeicherte Änderungen")).toBeInTheDocument();
    await advance(1300);
    await waitFor(() => expect(api.studioApi.saveDraft).toHaveBeenCalledTimes(1));
    expect(api.studioApi.saveDraft.mock.calls[0][1].brand_mode).toBe("pinned");
    expect(await screen.findByText("Gespeichert")).toBeInTheDocument();
  });

  it("deletes the selected element with the keyboard and restores it with undo", async () => {
    await renderDesigner();
    fireEvent.click(canvasNode("Einleitung"));
    fireEvent.keyDown(window, { key: "Delete" });
    await waitFor(() => expect(within(screen.getByRole("main", { name: "Arbeitsfläche" })).queryByRole("button", { name: "Einleitung" })).not.toBeInTheDocument());
    fireEvent.keyDown(window, { key: "z", ctrlKey: true });
    expect(await within(screen.getByRole("main", { name: "Arbeitsfläche" })).findByRole("button", { name: "Einleitung" })).toBeInTheDocument();
  });

  it("keeps locked elements when deleting", async () => {
    await renderDesigner();
    fireEvent.click(canvasNode("Prüfvermerk"));
    fireEvent.keyDown(window, { key: "Delete" });
    await advance(1300);
    expect(api.studioApi.saveDraft).not.toHaveBeenCalled();
    expect(canvasNode("Prüfvermerk")).toBeInTheDocument();
  });

  it("stops autosaving on a conflict and reloads the newer state on request", async () => {
    api.studioApi.saveDraft.mockRejectedValueOnce(new ApiError("Konflikt", "conflict", 409, { lock_version: 7 }));
    await renderDesigner();
    fireEvent.click(screen.getAllByRole("button", { name: "«Text» einfügen" })[0]);
    await advance(1300);
    expect(await screen.findByText("Jemand anderes hat diese Vorlage inzwischen geändert.")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "«Text» einfügen" })[0]);
    await advance(2000);
    expect(api.studioApi.saveDraft).toHaveBeenCalledTimes(1);

    api.studioApi.getTemplate.mockResolvedValue(detail({ draft_revision: revision({ lock_version: 7 }) }));
    fireEvent.click(screen.getByRole("button", { name: "Neuen Stand laden" }));
    await waitFor(() => expect(screen.queryByText("Jemand anderes hat diese Vorlage inzwischen geändert.")).not.toBeInTheDocument());
    fireEvent.click(screen.getAllByRole("button", { name: "«Text» einfügen" })[0]);
    await advance(1300);
    await waitFor(() => expect(api.studioApi.saveDraft).toHaveBeenCalledTimes(2));
    expect(api.studioApi.saveDraft.mock.calls[1][1].lock_version).toBe(7);
  });

  it("blocks publishing while the draft has errors and selects the faulty element", async () => {
    api.studioApi.getTemplate.mockResolvedValue(detail({ diagnostics: [{ node_id: "inner-1", severity: "error", code: "unknownBinding", detail: "foo.bar" }] }));
    await renderDesigner();
    fireEvent.click(screen.getByRole("button", { name: "Veröffentlichen" }));
    expect(toast).toHaveBeenCalledWith("Ein Fehler verhindert das Veröffentlichen.", "error");
    expect(confirm).not.toHaveBeenCalled();
    expect(api.studioApi.publish).not.toHaveBeenCalled();
    expect(await screen.findByText("Unbekanntes Datenfeld (foo.bar)")).toBeInTheDocument();
  });

  it("publishes after confirmation", async () => {
    confirm.mockResolvedValue(true);
    api.studioApi.publish.mockResolvedValue(detail({ draft_revision: null, published_revision: revision({ id: "rev-draft", status: "published" }) }));
    await renderDesigner();
    fireEvent.click(screen.getByRole("button", { name: "Veröffentlichen" }));
    await waitFor(() => expect(api.studioApi.publish).toHaveBeenCalledWith("tpl"));
    expect(toast).toHaveBeenCalledWith("Vorlage veröffentlicht.", "success");
    expect(await screen.findByText("Veröffentlicht")).toBeInTheDocument();
  });

  it("shows system templates read-only and offers a copy", async () => {
    api.studioApi.getTemplate.mockResolvedValue(detail({ origin: "system", system_key: "todos_standard", editable: false, draft_revision: null }));
    api.studioApi.duplicateTemplate.mockResolvedValue({ id: "copy-1" });
    await renderDesigner();
    expect(screen.getByText("Systemvorlagen sind schreibgeschützt. Erstelle eine Kopie, um sie anzupassen.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Veröffentlichen" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "«Text» einfügen" })[0]).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /Kopie|anpassen/ }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/documents/templates/copy-1"));
  });

  it("renders the binding preview with the real engine request", async () => {
    await renderDesigner();
    await advance(800);
    await waitFor(() => expect(api.previewDocument).toHaveBeenCalled());
    const [request, maxPages] = api.previewDocument.mock.calls.at(-1)!;
    expect(request).toMatchObject({ document_type: "todos", data_mode: "sample", protocol_id: null });
    expect(request.content.body).toHaveLength(3);
    expect(maxPages).toBe(12);
  });
  it("inserts data fields as bound text and lists as tables bound to the entry fields", async () => {
    await renderDesigner();
    fireEvent.click(screen.getByRole("tab", { name: "Daten" }));
    fireEvent.click(screen.getAllByRole("button", { name: "«Name der Organisation» einfügen" })[0]);
    fireEvent.click(screen.getAllByRole("button", { name: "«Aktive Mitglieder» einfügen" })[0]);
    await advance(1300);
    await waitFor(() => expect(api.studioApi.saveDraft).toHaveBeenCalled());
    const body = api.studioApi.saveDraft.mock.calls.at(-1)![1].content.body;
    expect(body.at(-2)).toMatchObject({ type: "text", content: { default: [{ t: "bind", path: "organization.name" }] } });
    const table = body.at(-1);
    expect(table).toMatchObject({ type: "table", source: "members.active" });
    expect(table.columns.length).toBeGreaterThan(0);
    expect(table.columns[0].cell.default[0].path).toMatch(/^item\./);
  });

  it("disables data fields the exporting person may not read", async () => {
    api.studioApi.capabilities.mockResolvedValue({ ...capabilities, finance_data: false });
    await renderDesigner();
    fireEvent.click(screen.getByRole("tab", { name: "Daten" }));
    expect(screen.getAllByRole("button", { name: "«Gesamtsaldo» einfügen" })[0]).toBeDisabled();
    expect(screen.getAllByRole("button", { name: "«Name der Organisation» einfügen" })[0]).toBeEnabled();
  });

  it("edits the text of the selected element in the properties panel", async () => {
    await renderDesigner();
    fireEvent.click(canvasNode("Einleitung"));
    const panel = screen.getByRole("complementary", { name: "Eigenschaften" });
    const segment = within(panel).getAllByRole("textbox", { name: "Text" })[0];
    expect(segment).toHaveValue("Einleitung");
    fireEvent.change(segment, { target: { value: "Willkommen" } });
    await advance(1300);
    await waitFor(() => expect(api.studioApi.saveDraft).toHaveBeenCalled());
    expect(api.studioApi.saveDraft.mock.calls.at(-1)![1].content.body[0].content.default[0]).toEqual({ t: "text", v: "Willkommen" });
  });
});
