import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ElementDefinition } from "@/types/api";

const api = vi.fn();
const toast = vi.fn();
const confirmMock = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (...args: unknown[]) => api(...args), browserApiBaseUrl: "" }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirmMock }));
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
    sort_index: id * 10, render_order: null,
    configuration_json: { title_as_subtitle: false, nested: { values: ["unverändert"] } },
  })),
};
const copy = { ...original, id: "copy", title: "Sitzungsinhalt (Kopie)" };

function setup(definitions: ElementDefinition[] = [original]) {
  render(<ElementDefinitionManager initialDefinitions={definitions} knownEventTags={[]} tenantId="tenant" />);
}

/** Zeilenmenü (⋮) eines Bausteins öffnen und einen Eintrag wählen. */
function chooseMenuItem(title: string, item: string) {
  fireEvent.click(screen.getByRole("button", { name: `Aktionen für «${title}»` }));
  fireEvent.click(screen.getByRole("menuitem", { name: item }));
}

beforeEach(() => { api.mockReset(); toast.mockReset(); confirmMock.mockReset(); });

describe("Elemente duplizieren", () => {
  it("übernimmt alle Blöcke und Einstellungen und öffnet die neue Kopie", async () => {
    api.mockResolvedValueOnce(copy);
    setup();
    chooseMenuItem(original.title, "Duplizieren");
    await waitFor(() => expect(screen.getByDisplayValue(copy.title)).toBeInTheDocument());
    const [path, options] = api.mock.calls[0];
    expect(path).toBe("/api/element-definitions");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({
      title: copy.title, description: original.description, is_active: true, blocks: original.blocks,
    });
    expect(screen.getByRole("button", { name: original.title })).toBeInTheDocument();
    expect(original.title).toBe("Sitzungsinhalt");
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("dupliziert"), "success");
  });

  it("sperrt weitere Klicks während des Speicherns und erlaubt nach Fehlern einen neuen Versuch", async () => {
    let reject!: (error: Error) => void;
    api.mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; }));
    setup();
    chooseMenuItem(original.title, "Duplizieren");
    chooseMenuItem(original.title, "Duplizieren");
    expect(api).toHaveBeenCalledTimes(1);
    reject(new Error("Speichern fehlgeschlagen"));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Speichern fehlgeschlagen", "error"));
    expect(screen.queryByDisplayValue(copy.title)).not.toBeInTheDocument();
    api.mockResolvedValueOnce(copy);
    chooseMenuItem(original.title, "Duplizieren");
    await waitFor(() => expect(screen.getByDisplayValue(copy.title)).toBeInTheDocument());
  });
});

describe("Block bearbeiten", () => {
  it("zeigt die Verhalten-Schalter wie beim Anlegen und speichert sie (B2)", async () => {
    api.mockImplementation((path: string, options?: { method?: string; body?: string }) => {
      if (path === "/api/cycle-configs") return Promise.resolve([]);
      if (options?.method === "PATCH") return Promise.resolve({ ...original, blocks: JSON.parse(options.body ?? "{}").blocks });
      return Promise.resolve(null);
    });
    setup();
    fireEvent.click(screen.getByRole("button", { name: original.title }));
    fireEvent.click(screen.getByRole("button", { name: /^Block 1/ }));
    // Die Schalter liegen auf der Seite «Verhalten» des Block-Dialogs
    fireEvent.click(await screen.findByRole("button", { name: /^Verhalten/ }));
    const exportSwitch = await screen.findByRole("checkbox", { name: /Im PDF ausgeben/ });
    expect(screen.getByRole("checkbox", { name: /Im Protokoll bearbeitbar/ })).not.toBeChecked();
    fireEvent.click(exportSwitch);
    fireEvent.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(api.mock.calls.some(([, options]) => options?.method === "PATCH")).toBe(true));
    const patch = api.mock.calls.find(([, options]) => options?.method === "PATCH")!;
    const saved = JSON.parse(patch[1].body).blocks.find((entry: { id: number }) => entry.id === 1);
    expect(saved.export_visible).toBe(false);
    expect(saved.copy_from_last_protocol).toBe(true);
  });
});

function definitionWith(overrides: Partial<ElementDefinition>): ElementDefinition {
  return { ...original, ...overrides };
}

describe("Bausteinliste", () => {
  it("zeigt Platzhalter im Namen als Pille mit Hinweis", () => {
    setup([definitionWith({ id: "p", title: "Jahresprogramm {cycle_year_start}" })]);
    const pill = screen.getByText("{cycle_year_start}");
    expect(pill.tagName).toBe("CODE");
    expect(pill).toHaveClass("element-library-placeholder");
    expect(pill).toHaveAttribute("title", "Wird beim Einfügen ersetzt");
    expect(screen.getByText("Jahresprogramm", { exact: false }).tagName).toBe("SPAN");
  });

  it("leitet die Inhalt-Chips eindeutig und in Blockreihenfolge ab", () => {
    const block = original.blocks[0];
    setup([definitionWith({
      id: "c",
      blocks: [
        { ...block, id: 1, element_type_id: 7, sort_index: 30 },
        { ...block, id: 2, element_type_id: 1, sort_index: 10 },
        { ...block, id: 3, element_type_id: 6, sort_index: 20 },
        { ...block, id: 4, element_type_id: 1, sort_index: 40 },
      ],
    })]);
    const row = screen.getByRole("row", { name: /Sitzungsinhalt/ });
    const chips = row.querySelectorAll(".badge");
    expect([...chips].map((chip) => chip.textContent)).toEqual(["Text", "Tabelle", "Terminliste"]);
  });

  it("zeigt die Verwendung in Vorlagen", () => {
    setup([
      definitionWith({ id: "a", title: "Ungenutzt", template_count: 0 }),
      definitionWith({ id: "b", title: "Einmal", template_count: 1 }),
      definitionWith({ id: "c", title: "Oft", template_count: 3 }),
    ]);
    expect(within(screen.getByRole("row", { name: /Ungenutzt/ })).getByText("—")).toBeInTheDocument();
    expect(within(screen.getByRole("row", { name: /Einmal/ })).getByText("1 Vorlage")).toBeInTheDocument();
    expect(within(screen.getByRole("row", { name: /Oft/ })).getByText("3 Vorlagen")).toBeInTheDocument();
  });

  it("zählt die gefilterten Bausteine und zeigt ohne Treffer den Leerzustand", () => {
    setup([definitionWith({ id: "a", title: "Begrüssung" }), definitionWith({ id: "b", title: "Jahresprogramm" })]);
    expect(screen.getByText("2 Bausteine")).toBeInTheDocument();
    const search = screen.getByPlaceholderText("Bausteine durchsuchen");
    fireEvent.change(search, { target: { value: "jahres" } });
    expect(screen.getByText("1 Baustein")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Begrüssung" })).not.toBeInTheDocument();
    fireEvent.change(search, { target: { value: "gibt es nicht" } });
    expect(screen.getByText("0 Bausteine")).toBeInTheDocument();
    expect(screen.getByText("Keine Bausteine gefunden.")).toBeInTheDocument();
  });

  it("öffnet den Baustein über das Menü «Bearbeiten»", () => {
    setup();
    chooseMenuItem(original.title, "Bearbeiten");
    expect(screen.getByDisplayValue(original.title)).toBeInTheDocument();
  });

  it("zeigt «Löschen» abgesetzt als Gefahr und löscht erst nach Bestätigung", async () => {
    confirmMock.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    api.mockResolvedValue({ message: "ok" });
    setup();
    fireEvent.click(screen.getByRole("button", { name: `Aktionen für «${original.title}»` }));
    const remove = screen.getByRole("menuitem", { name: "Löschen" });
    expect(remove).toHaveClass("action-menu-item-danger");
    expect(remove.previousElementSibling).toHaveAttribute("role", "separator");
    fireEvent.click(remove);
    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({ tone: "danger", message: expect.stringContaining(`Baustein «${original.title}» löschen?`) }));
    expect(api).not.toHaveBeenCalled();
    chooseMenuItem(original.title, "Löschen");
    await waitFor(() => expect(api).toHaveBeenCalledWith(`/api/element-definitions/${original.id}`, { method: "DELETE" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: original.title })).not.toBeInTheDocument());
  });
});

describe("Dialog «Baustein bearbeiten»", () => {
  function openDialog(definition: ElementDefinition = original) {
    setup([definition]);
    fireEvent.click(screen.getByRole("button", { name: definition.title }));
    return screen.getByRole("dialog", { name: `Element bearbeiten: ${definition.title}` });
  }

  it("zeigt Titel inline, Blöcke mit Nummer, Typ-Chip und Überschrift", () => {
    const dialog = openDialog(definitionWith({
      blocks: [
        { ...original.blocks[0], id: 1, title: "Programm {cycle_year_start}", block_title: "Ablauf", element_type_id: 6, sort_index: 10 },
        { ...original.blocks[1], id: 2, title: "Notiz", block_title: null, sort_index: 20 },
      ],
    }));
    expect(within(dialog).getByRole("textbox", { name: "Elementtitel" })).toHaveValue(original.title);
    expect(within(dialog).getByText("2 Blöcke · Klick öffnet, Ziehen sortiert")).toBeInTheDocument();
    const rows = dialog.querySelectorAll(".element-definition-block");
    expect(rows[0].querySelector(".element-definition-number")?.textContent).toBe("01");
    expect(within(rows[0] as HTMLElement).getByText("{cycle_year_start}").tagName).toBe("CODE");
    expect(within(rows[0] as HTMLElement).getByText("Tabelle")).toHaveClass("badge");
    expect(within(rows[0] as HTMLElement).getByText("Überschrift: Ablauf")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("Ohne eigene Überschrift")).toBeInTheDocument();
  });

  it("fügt Platzhalter an der Cursorposition ein und sperrt Speichern ohne Titel", () => {
    const dialog = openDialog();
    const input = within(dialog).getByRole("textbox", { name: "Elementtitel" }) as HTMLInputElement;
    input.setSelectionRange(6, 6);
    fireEvent.click(within(dialog).getByRole("button", { name: "{cycle_year_start}" }));
    expect(input).toHaveValue("Sitzun {cycle_year_start}gsinhalt");
    fireEvent.change(input, { target: { value: "" } });
    expect(within(dialog).getByRole("button", { name: "Speichern" })).toBeDisabled();
  });

  it("bestätigt Löschen inline in der Zeile", async () => {
    api.mockImplementation((_path: string, options?: { body?: string }) => Promise.resolve({ ...original, blocks: JSON.parse(options?.body ?? "{}").blocks }));
    const dialog = openDialog();
    fireEvent.click(within(dialog).getAllByRole("button", { name: "Block löschen" })[0]);
    expect(within(dialog).getByText("Block löschen?")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Nein" }));
    expect(api).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getAllByRole("button", { name: "Block löschen" })[0]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Löschen" }));
    await waitFor(() => expect(api).toHaveBeenCalled());
    const [path, options] = api.mock.calls[0];
    expect(path).toBe(`/api/element-definitions/${original.id}`);
    expect(JSON.parse(options.body).blocks.map((block: { id: number }) => block.id)).toEqual([2]);
    expect(confirmMock).not.toHaveBeenCalled();
  });

  it("sortiert per Alt+Pfeil und speichert sofort", async () => {
    api.mockImplementation((_path: string, options?: { body?: string }) => Promise.resolve({ ...original, blocks: JSON.parse(options?.body ?? "{}").blocks }));
    const dialog = openDialog();
    fireEvent.keyDown(within(dialog).getByRole("button", { name: /^Block 1/ }), { key: "ArrowDown", altKey: true });
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(JSON.parse(api.mock.calls[0][1].body).blocks.map((block: { id: number }) => block.id)).toEqual([2, 1]);
  });
});
