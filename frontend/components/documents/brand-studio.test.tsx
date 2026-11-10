import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import studio from "@/lib/documents/test/studio-catalog.generated.json";

import { BrandStudio } from "./brand-studio";

const api = vi.hoisted(() => ({
  previewDocument: vi.fn(),
  studioApi: {
    brands: vi.fn(),
    assets: vi.fn(),
    catalog: vi.fn(),
    updateBrand: vi.fn(),
    createBrand: vi.fn(),
    archiveBrand: vi.fn(),
    documentSettings: vi.fn(),
    updateDocumentSettings: vi.fn(),
  },
}));
const { toast, confirm } = vi.hoisted(() => ({ toast: vi.fn(), confirm: vi.fn() }));

vi.mock("@/lib/documents/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/documents/api")>()), ...api }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirm }));

const capabilities = { export: true, view_templates: true, edit_templates: true, publish_templates: true, manage_brand: true, finance_data: true, personal_data: true };

function brand(id: string, overrides: Record<string, unknown> = {}) {
  return { id, name: id === "b1" ? "Verein" : "Jubiläum", description: null, is_default: id === "b1", archived: false, revision: 3, lock_version: 5, tokens: structuredClone(studio.brand_tokens), updated_at: "", ...overrides };
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** Farbfeld öffnen, Hex-Wert eingeben und den Farbwähler wieder schliessen. */
async function setColor(label: string, hex: string) {
  fireEvent.click(await screen.findByRole("button", { name: label }));
  const dialog = screen.getByRole("dialog", { name: label });
  fireEvent.change(within(dialog).getByLabelText("Hex-Wert"), { target: { value: hex } });
  fireEvent.keyDown(window, { key: "Escape" });
}

describe("BrandStudio", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    [toast, confirm, api.previewDocument, ...Object.values(api.studioApi)].forEach((fn) => fn.mockReset());
    api.studioApi.brands.mockResolvedValue([brand("b1"), brand("b2")]);
    api.studioApi.assets.mockResolvedValue([]);
    api.studioApi.catalog.mockResolvedValue(studio.catalog);
    api.previewDocument.mockResolvedValue({ pages: ["data:image/png;base64,AAA"], page_count: 1, diagnostics: [] });
    api.studioApi.documentSettings.mockResolvedValue({ language: "de" });
  });

  it("previews unsaved changes and saves them with the lock version", async () => {
    api.studioApi.updateBrand.mockImplementation(async (id: string, body: { name: string; tokens: unknown }) => ({ ...brand(id), name: body.name, tokens: body.tokens, revision: 4, lock_version: 6 }));
    render(<BrandStudio capabilities={capabilities} />);
    const name = await screen.findByLabelText("Name");
    expect(name).toHaveValue("Verein");
    expect(screen.getByRole("button", { name: "Speichern" })).toBeDisabled();

    fireEvent.change(name, { target: { value: "Verein Seetal" } });
    fireEvent.change(screen.getByLabelText(/^Grundgrösse/), { target: { value: "11" } });
    await advance(800);
    await waitFor(() => expect(api.previewDocument.mock.calls.at(-1)![0].brand_tokens.typography.base_size).toBe(11));
    expect(api.previewDocument.mock.calls.at(-1)![0]).toMatchObject({ document_type: "protocol", data_mode: "sample", brand_id: null });

    fireEvent.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(api.studioApi.updateBrand).toHaveBeenCalled());
    const [id, body] = api.studioApi.updateBrand.mock.calls[0];
    expect(id).toBe("b1");
    expect(body).toMatchObject({ lock_version: 5, name: "Verein Seetal" });
    expect(body.tokens.typography.base_size).toBe(11);
    expect(toast).toHaveBeenCalledWith("Gespeichert als Version 4.", "success");
  });

  it("derives the remaining colors from the two main colors until one is changed by hand", async () => {
    render(<BrandStudio capabilities={capabilities} />);
    await setColor("Hauptfarbe", "#aa0000");
    await advance(800);
    await waitFor(() => expect(api.previewDocument.mock.calls.at(-1)![0].brand_tokens.colors).toMatchObject({ primary: "#AA0000", heading: "#AA0000", table_header_background: "#F7E6E6" }));

    await setColor("Linien", "#123456");
    expect(screen.getByLabelText("Übrige Farben automatisch ableiten")).not.toBeChecked();
    await setColor("Hauptfarbe", "#00aa00");
    await advance(800);
    await waitFor(() => expect(api.previewDocument.mock.calls.at(-1)![0].brand_tokens.colors).toMatchObject({ primary: "#00AA00", heading: "#AA0000", border: "#123456" }));
  });

  it("applies a base style and keeps element overrides on top of it", async () => {
    render(<BrandStudio capabilities={capabilities} />);
    // Frühere Grundstile stehen nur noch Profilen zur Wahl, die sie nutzen
    expect(await screen.findByRole("radio", { name: /Signal/ })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /Abgerundet/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: /Signal/ }));
    fireEvent.change(screen.getByLabelText("Anwesenheit"), { target: { value: "chips" } });
    await advance(800);
    // Ein Design übernimmt auch Abschnittsnummer und Verantwortliche in den Seitenaufbau
    await waitFor(() => expect(api.previewDocument.mock.calls.at(-1)![0].brand_tokens).toMatchObject({
      appearance: { base: "signal", elements: { attendance: { variant: "chips", corners: null } } },
      layout: { heading_style: "boxed", table_style: "grid", radius: 0, heading_number_style: "accent", responsible_display: "right" },
    }));
    fireEvent.click(screen.getByRole("radio", { name: /Klassisch/ }));
    await advance(800);
    await waitFor(() => expect(api.previewDocument.mock.calls.at(-1)![0].brand_tokens.appearance).toEqual({ base: "classic", elements: { attendance: { variant: "chips", corners: null } } }));
  });

  it("reports a parallel change instead of overwriting it", async () => {
    api.studioApi.updateBrand.mockRejectedValue(new ApiError("Konflikt", "conflict", 409, { lock_version: 9 }));
    render(<BrandStudio capabilities={capabilities} />);
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "Neu" } });
    fireEvent.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Das Profil wurde inzwischen geändert. Bitte neu laden.", "error"));
  });

  it("asks before switching profiles with unsaved changes", async () => {
    confirm.mockResolvedValue(false);
    render(<BrandStudio capabilities={capabilities} />);
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "Geändert" } });
    fireEvent.click(screen.getByRole("button", { name: "Jubiläum" }));
    await waitFor(() => expect(confirm).toHaveBeenCalled());
    expect(screen.getByLabelText("Name")).toHaveValue("Geändert");
  });

  it("creates a profile from a preset", async () => {
    api.studioApi.createBrand.mockResolvedValue(brand("b3", { name: "Sommerfest", is_default: false }));
    render(<BrandStudio capabilities={capabilities} />);
    fireEvent.click(await screen.findByRole("button", { name: "Weiteres Profil" }));
    fireEvent.change(screen.getAllByLabelText("Name").at(-1)!, { target: { value: "Sommerfest" } });
    fireEvent.click(screen.getByRole("radio", { name: /Wald/ }));
    fireEvent.click(screen.getByRole("button", { name: "Erstellen" }));
    await waitFor(() => expect(api.studioApi.createBrand).toHaveBeenCalledWith({ name: "Sommerfest", preset: "forest" }));
    expect(toast).toHaveBeenCalledWith("Profil erstellt.", "success");
  });

  it("is read-only without brand permission and previews the saved profile", async () => {
    render(<BrandStudio capabilities={{ ...capabilities, manage_brand: false }} />);
    expect(await screen.findByText("Nur Administratoren können das Corporate Design ändern.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Speichern" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Weiteres Profil" })).not.toBeInTheDocument();
    await advance(800);
    await waitFor(() => expect(api.previewDocument).toHaveBeenCalled());
    expect(api.previewDocument.mock.calls.at(-1)![0]).toMatchObject({ brand_tokens: null, brand_id: "b1" });
  });
  it("lists unused profiles separately and archives them together", async () => {
    api.studioApi.brands.mockResolvedValue([brand("b1", { template_count: 4 }), brand("b2", { template_count: 0 }), brand("b3", { name: "Gruppe", template_count: 2 })]);
    api.studioApi.archiveBrand.mockResolvedValue(brand("b2", { archived: true }));
    render(<BrandStudio capabilities={capabilities} />);
    expect(await screen.findByText("Wirkt auf 4 Vorlagen · Version 3")).toBeInTheDocument();
    expect(screen.getByText("Nicht verwendet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Archivieren" }));
    await waitFor(() => expect(api.studioApi.archiveBrand).toHaveBeenCalledWith("b2", true));
    expect(api.studioApi.archiveBrand).toHaveBeenCalledTimes(1);
    expect(toast).toHaveBeenCalledWith("1 Profil archiviert", "success");
  });

  it("previews the club's template of the chosen document type", async () => {
    render(<BrandStudio capabilities={capabilities} />);
    await screen.findByLabelText("Name");
    fireEvent.click(screen.getByRole("tab", { name: "Einladung" }));
    await advance(800);
    await waitFor(() => expect(api.previewDocument.mock.calls.at(-1)![0]).toMatchObject({ document_type: "invitation", data_mode: "sample" }));
    expect(api.previewDocument.mock.calls.at(-1)![0].template_id).toBeUndefined();
  });

  it("saves the document language of the organisation", async () => {
    api.studioApi.updateDocumentSettings.mockResolvedValue({ language: "fr" });
    render(<BrandStudio capabilities={capabilities} />);
    const select = await screen.findByLabelText(/^Dokumentsprache des Vereins/);
    await waitFor(() => expect(select).toHaveValue("de"));
    fireEvent.change(select, { target: { value: "fr" } });
    await waitFor(() => expect(api.studioApi.updateDocumentSettings).toHaveBeenCalledWith("fr"));
    expect(toast).toHaveBeenCalledWith("Dokumentsprache gespeichert.", "success");
  });
});
