import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FileOverviewItem } from "@/types/api";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

vi.mock("@/contexts/toast-context", () => ({
  useToast: () => showToastMock,
}));

import { countFrequentTags, FileDetailModal } from "./file-detail-modal";

function makeItem(overrides: Partial<FileOverviewItem> = {}): FileOverviewItem {
  return {
    id: "file-1",
    original_name: "programm.zip",
    mime_type: "application/zip",
    file_size_bytes: 17408,
    created_at: "2026-10-01T10:00:00Z",
    source: "gallery_upload",
    is_image: false,
    content_url: "/api/stored-files/file-1/content",
    thumbnail_url: null,
    tags_url: "/api/stored-files/file-1/tags",
    metadata_url: "/api/stored-files/file-1/metadata",
    ref_label: "",
    ref_date: null,
    ref_end_date: null,
    ref_href: null,
    tags: ["Lager"],
    origin_tag: "Direkt hochgeladen",
    sharpness_score: null,
    exposure_score: null,
    face_quality_score: null,
    face_analyzed_at: null,
    width: null,
    height: null,
    group_date: null,
    context_label: null,
    live_video_url: null,
    albums: [],
    document: null,
    is_best: null,
    ...overrides,
  } as FileOverviewItem;
}

const noop = () => {};

describe("FileDetailModal v2", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
  });

  it("benennt die Datei inline um, die Endung bleibt", async () => {
    browserApiFetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/name")) return { original_name: JSON.parse(String(init?.body)).name };
      return null;
    });
    const onRenamed = vi.fn();
    render(<FileDetailModal item={makeItem()} tagSuggestions={[]} onClose={noop} onNavigate={noop} onTagsSaved={noop} canManage onRenamed={onRenamed} />);

    fireEvent.click(screen.getByRole("button", { name: /programm\.zip/ }));
    const input = screen.getByLabelText("Dateiname") as HTMLInputElement;
    expect(input.value).toBe("programm");
    fireEvent.change(input, { target: { value: "Programm 2026" } });
    fireEvent.click(screen.getByRole("button", { name: "Speichern" }));

    await waitFor(() => expect(onRenamed).toHaveBeenCalledWith("Programm 2026.zip"));
    expect(browserApiFetchMock).toHaveBeenCalledWith("/api/stored-files/file-1/name", { method: "PATCH", body: JSON.stringify({ name: "Programm 2026.zip" }) });
    expect(showToastMock).toHaveBeenCalledWith("Datei umbenannt.", "success");
  });

  it("Esc bricht das Umbenennen ab, ohne das Popup zu schliessen", async () => {
    browserApiFetchMock.mockResolvedValue(null);
    const onClose = vi.fn();
    render(<FileDetailModal item={makeItem()} tagSuggestions={[]} onClose={onClose} onNavigate={noop} onTagsSaved={noop} canManage />);
    fireEvent.click(screen.getByRole("button", { name: /programm\.zip/ }));
    fireEvent.keyDown(screen.getByLabelText("Dateiname"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByLabelText("Dateiname")).not.toBeInTheDocument());
    expect(onClose).not.toHaveBeenCalled();
  });

  it("ohne Recht kein Umbenennen und kein Papierkorb, sondern ein Hinweis", () => {
    browserApiFetchMock.mockResolvedValue(null);
    render(<FileDetailModal item={makeItem()} tagSuggestions={[]} onClose={noop} onNavigate={noop} onTagsSaved={noop} />);
    expect(screen.queryByRole("button", { name: /programm\.zip/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /In den Papierkorb/ })).not.toBeInTheDocument();
    expect(screen.getByText("Löschen braucht die Berechtigung «Dateien verwalten».")).toBeInTheDocument();
  });

  it("ohne Recht keine Tag-Bearbeitung (Nachtlauf 2026-11-22: PATCH /tags lehnte mit 403 ab)", () => {
    browserApiFetchMock.mockResolvedValue(null);
    render(<FileDetailModal item={makeItem({ tags: [] })} tagSuggestions={["Lager"]} frequentTags={["Lager", "Bericht"]} onClose={noop} onNavigate={noop} onTagsSaved={noop} />);
    expect(screen.queryByPlaceholderText("Tag hinzufügen…")).not.toBeInTheDocument();
    expect(screen.queryByText("Häufig:")).not.toBeInTheDocument();
  });

  it("legt nach Bestätigung im Fuss in den Papierkorb und stellt wieder her", async () => {
    browserApiFetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/files/trash" || url === "/api/files/trash/restore") return { file_ids: ["file-1"], errors: [] };
      return null;
    });
    const onTrashed = vi.fn();
    render(
      <FileDetailModal item={makeItem()} tagSuggestions={[]} onClose={noop} onNavigate={noop} onTagsSaved={noop} canManage onTrashed={onTrashed}
        onStep={noop} position={{ index: 0, total: 2 }} />
    );

    fireEvent.click(screen.getByRole("button", { name: /In den Papierkorb/ }));
    expect(screen.getByText("In den Papierkorb legen?")).toBeInTheDocument();
    expect(browserApiFetchMock).not.toHaveBeenCalledWith("/api/files/trash", expect.anything());
    fireEvent.click(screen.getByRole("button", { name: "Abbrechen" }));
    expect(screen.queryByText("In den Papierkorb legen?")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /In den Papierkorb/ }));
    fireEvent.click(screen.getAllByRole("button", { name: /In den Papierkorb/ }).at(-1)!);
    expect(await screen.findByText("Liegt im Papierkorb")).toBeInTheDocument();
    expect(browserApiFetchMock).toHaveBeenCalledWith("/api/files/trash", { method: "POST", body: JSON.stringify({ file_ids: ["file-1"] }) });
    expect(screen.getByRole("button", { name: "Nächste Datei →" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Wiederherstellen" }));
    await waitFor(() => expect(screen.queryByText("Liegt im Papierkorb")).not.toBeInTheDocument());
    expect(onTrashed).not.toHaveBeenCalled();
  });

  it("blättert nach dem Löschen weiter und meldet die Datei als entfernt", async () => {
    browserApiFetchMock.mockImplementation(async (url: string) => (url === "/api/files/trash" ? { file_ids: ["file-1"], errors: [] } : null));
    const onStep = vi.fn();
    const onTrashed = vi.fn();
    render(
      <FileDetailModal item={makeItem()} tagSuggestions={[]} onClose={noop} onNavigate={noop} onTagsSaved={noop} canManage onTrashed={onTrashed}
        onStep={onStep} position={{ index: 0, total: 2 }} />
    );
    fireEvent.click(screen.getByRole("button", { name: /In den Papierkorb/ }));
    fireEvent.click(screen.getAllByRole("button", { name: /In den Papierkorb/ }).at(-1)!);
    fireEvent.click(await screen.findByRole("button", { name: "Nächste Datei →" }));
    await waitFor(() => expect(onStep).toHaveBeenCalledWith(1));
    expect(onTrashed).toHaveBeenCalledWith(expect.objectContaining({ id: "file-1" }));
  });

  it("fügt Schnell-Tags hinzu und speichert vor dem Blättern", async () => {
    browserApiFetchMock.mockImplementation(async (url: string, init?: RequestInit) =>
      url.endsWith("/tags") ? JSON.parse(String(init?.body)).tags : null,
    );
    const onTagsSaved = vi.fn();
    const onStep = vi.fn();
    render(
      <FileDetailModal item={makeItem()} tagSuggestions={[]} frequentTags={["Lager", "Bericht"]} onClose={noop} onNavigate={noop}
        onTagsSaved={onTagsSaved} onStep={onStep} position={{ index: 0, total: 2 }} canManage />
    );
    expect(screen.getByText("Häufig:")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Bericht" }));
    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() => expect(onStep).toHaveBeenCalledWith(1));
    expect(onTagsSaved).toHaveBeenCalledWith(["Lager", "Bericht"]);
  });

  it("bietet beim Tippen eines neuen Tags «neu erstellen» an", () => {
    browserApiFetchMock.mockResolvedValue(null);
    render(<FileDetailModal item={makeItem({ tags: [] })} tagSuggestions={["Lager"]} onClose={noop} onNavigate={noop} onTagsSaved={noop} canManage />);
    const field = screen.getByPlaceholderText("Tag hinzufügen…");
    fireEvent.focus(field);
    fireEvent.change(field, { target: { value: "Neu" } });
    expect(screen.getByRole("button", { name: "«Neu» neu erstellen" })).toBeInTheDocument();
  });
});

describe("countFrequentTags", () => {
  it("zählt nur mehrfach verwendete Tags, häufigste zuerst", () => {
    const items = [makeItem({ tags: ["A", "B"] }), makeItem({ tags: ["B", "C"] }), makeItem({ tags: ["B", "A"] }), makeItem({ tags: ["D"] })];
    expect(countFrequentTags(items)).toEqual(["B", "A"]);
  });
});
