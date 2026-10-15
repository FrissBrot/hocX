import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    listTemplates: vi.fn(),
    updateBrand: vi.fn(),
    createBrand: vi.fn(),
    documentSettings: vi.fn(),
    updateDocumentSettings: vi.fn(),
  },
}));
const { toast, confirm } = vi.hoisted(() => ({ toast: vi.fn(), confirm: vi.fn() }));

vi.mock("@/lib/documents/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/documents/api")>()), ...api }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirm }));

const capabilities = { export: true, view_templates: true, edit_templates: true, publish_templates: true, manage_brand: true, finance_data: true, personal_data: true };
const published = { id: "rev", revision_no: 1, status: "published", lock_version: 1, brand_mode: "follow", schema_version: 1, note: null, created_at: "", updated_at: "", published_at: "", created_by_name: null, template_id: null, brand_id: null };

function brand(id: string, overrides: Record<string, unknown> = {}) {
  return { id, name: id === "b1" ? "Verein" : "Jubiläum", description: null, is_default: id === "b1", archived: false, revision: 3, lock_version: 5, tokens: structuredClone(studio.brand_tokens), updated_at: "", ...overrides };
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("BrandStudio", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    [toast, confirm, api.previewDocument, ...Object.values(api.studioApi)].forEach((fn) => fn.mockReset());
    api.studioApi.brands.mockResolvedValue([brand("b1"), brand("b2")]);
    api.studioApi.assets.mockResolvedValue([]);
    api.studioApi.catalog.mockResolvedValue(studio.catalog);
    api.studioApi.listTemplates.mockResolvedValue([
      { id: "tpl-formal", system_key: "protocol_formal", document_type: "protocol", status: "active", published_revision: published, origin: "system", name: "x" },
    ]);
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
    expect(api.previewDocument.mock.calls.at(-1)![0]).toMatchObject({ template_id: "tpl-formal", data_mode: "sample", brand_id: null });

    fireEvent.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(api.studioApi.updateBrand).toHaveBeenCalled());
    const [id, body] = api.studioApi.updateBrand.mock.calls[0];
    expect(id).toBe("b1");
    expect(body).toMatchObject({ lock_version: 5, name: "Verein Seetal" });
    expect(body.tokens.typography.base_size).toBe(11);
    expect(toast).toHaveBeenCalledWith("Gespeichert als Version 4.", "success");
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
    fireEvent.click(await screen.findByRole("button", { name: "Neues Profil" }));
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
    expect(screen.queryByRole("button", { name: "Neues Profil" })).not.toBeInTheDocument();
    await advance(800);
    await waitFor(() => expect(api.previewDocument).toHaveBeenCalled());
    expect(api.previewDocument.mock.calls.at(-1)![0]).toMatchObject({ brand_tokens: null, brand_id: "b1" });
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
