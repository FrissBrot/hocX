import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TodoListItem } from "@/types/api";

const api = vi.hoisted(() => vi.fn());
const upload = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => vi.fn());
const choice = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({
  ApiError: class ApiError extends Error {},
  browserApiFetch: (url: string, init?: { method?: string; body?: string }) => api(url, init),
  browserApiUpload: (url: string, body: FormData, options: unknown) => upload(url, body, options),
}));
vi.mock("@/lib/image-analysis/precheck", () => ({
  hashForPrecheck: async (file: File) => ({ sha256: `sha-${file.name}`, analysis: "ok" }),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn().mockResolvedValue(true), useChoice: () => choice }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/ui/rich-text-editor", () => ({
  RichTextEditor: ({ value, onChange }: { value: string; onChange: (value: string) => void }) =>
    <textarea aria-label="Notizen-Editor" value={value} onChange={(event) => onChange(event.target.value)} />,
}));

import { TodoEditModal } from "./todo-edit-modal";
import { TodoFilePicker } from "./todo-file-picker";

const todo = { id: "todo-1", task: "Budget prüfen", tags: [], todo_status_id: 1, todo_status_code: "open", assigned_participant_id: null, protocol_id: null } as TodoListItem;
const existing = {
  id: "file-old", original_name: "Budget.pdf", mime_type: "application/pdf", file_size_bytes: 1200, content_url: "/api/stored-files/file-old/content",
  created_at: "2026-11-02T10:00:00Z", ref_label: "Vorstand", origin_tag: "Direkt hochgeladen",
};
const uploaded = { ...existing, id: "file-new", original_name: "Budget.pdf", content_url: "/api/stored-files/file-new/content" };

let duplicateMatches: unknown[] = [];

beforeEach(() => {
  vi.clearAllMocks();
  duplicateMatches = [];
  api.mockImplementation((url: string, init?: { method?: string }) => {
    if (url.endsWith("/details") && !init?.method) return Promise.resolve({ notes: "", files: [] });
    if (url === "/api/files/duplicate-check") return Promise.resolve({ matches: duplicateMatches });
    if (url.startsWith("/api/files")) return Promise.resolve([existing]);
    if (url.endsWith("/submission")) return Promise.resolve(null);
    return Promise.resolve({});
  });
  upload.mockResolvedValue({ items: [uploaded], errors: [], file_results: [] });
});
afterEach(cleanup);

function mount(props: Partial<Parameters<typeof TodoEditModal>[0]> = {}) {
  render(<TodoEditModal todo={todo} canEdit participants={[]} tagSuggestions={[]} onSaved={vi.fn()} onClose={vi.fn()} onDeleted={vi.fn()} canUploadFiles {...props} />);
}

function fileTransfer(files: File[], types = ["Files"]) {
  return { dataTransfer: { types, files, dropEffect: "none" } };
}

async function dialogShell() {
  // Shell des aktuellen Dialogs (nicht irgendein .modal-shell im Dokument)
  const shell = (await screen.findByPlaceholderText("Hochgeladene Datei suchen …")).closest(".modal-shell");
  if (!(shell instanceof HTMLElement)) throw new Error("no modal shell");
  return shell;
}

describe("Pendenz-Dialog als Dropzone", () => {
  it("zeigt das Overlay nur für Dateien und hält es über Kind-Elemente hinweg", async () => {
    mount();
    const shell = await dialogShell();
    const child = within(shell).getByPlaceholderText("Hochgeladene Datei suchen …");

    fireEvent.dragEnter(shell, fileTransfer([], ["text/plain"]));
    expect(screen.queryByTestId("todo-drop-overlay")).toBeNull();

    fireEvent.dragEnter(shell, fileTransfer([]));
    expect(screen.getByText("Loslassen zum Anhängen")).toBeInTheDocument();
    fireEvent.dragEnter(child, fileTransfer([]));
    fireEvent.dragLeave(shell, fileTransfer([]));
    expect(screen.getByTestId("todo-drop-overlay")).toBeInTheDocument();
    fireEvent.dragLeave(child, fileTransfer([]));
    expect(screen.queryByTestId("todo-drop-overlay")).toBeNull();
  });

  it("ohne files.manage gibt es weder Dropzone noch Hinweis", async () => {
    mount({ canUploadFiles: false });
    const shell = await dialogShell();
    fireEvent.dragEnter(shell, fileTransfer([]));
    expect(screen.queryByTestId("todo-drop-overlay")).toBeNull();
    expect(screen.queryByText("oder ins Fenster ziehen")).toBeNull();
  });

  it("lädt eine neue Datei hoch und hängt sie an (Kopie erlaubt, kein Orakel)", async () => {
    mount();
    expect(await screen.findByText("oder ins Fenster ziehen")).toBeInTheDocument();
    const shell = await dialogShell();
    const file = new File(["%PDF-1.7"], "Budget.pdf", { type: "application/pdf" });

    fireEvent.dragEnter(shell, fileTransfer([file]));
    fireEvent.drop(shell, fileTransfer([file]));

    expect(screen.queryByTestId("todo-drop-overlay")).toBeNull();
    await waitFor(() => expect(upload).toHaveBeenCalledOnce());
    expect(api).toHaveBeenCalledWith("/api/files/duplicate-check", expect.objectContaining({ method: "POST", body: JSON.stringify({ sha256: ["sha-Budget.pdf"] }) }));
    const body = upload.mock.calls[0][1] as FormData;
    expect(upload.mock.calls[0][0]).toBe("/api/files/document-uploads");
    expect(body.get("allow_duplicates")).toBe("true");
    expect(body.get("allow_images")).toBeNull();
    expect(choice).not.toHaveBeenCalled();
    expect(await screen.findByRole("link", { name: /Budget\.pdf/ })).toHaveAttribute("href", "/api/stored-files/file-new/content");
  });

  it("Bilder nur mit photos.manage als Bild hochladen", async () => {
    mount({ canUploadImages: true });
    const shell = await dialogShell();
    const file = new File(["png"], "foto.png", { type: "image/png" });
    fireEvent.drop(shell, fileTransfer([file]));
    await waitFor(() => expect(upload).toHaveBeenCalledOnce());
    expect((upload.mock.calls[0][1] as FormData).get("allow_images")).toBe("true");
  });

  it("Duplikat: «Bestehende anhängen» verknüpft ohne zweiten Upload", async () => {
    duplicateMatches = [{ sha256: "sha-Budget.pdf", file: existing }];
    choice.mockResolvedValue("confirm");
    mount();
    const shell = await dialogShell();
    fireEvent.drop(shell, fileTransfer([new File(["x"], "Budget.pdf")]));

    await waitFor(() => expect(choice).toHaveBeenCalledOnce());
    expect(choice.mock.calls[0][0]).toMatchObject({
      title: "Datei bereits vorhanden",
      message: "Diese Datei gibt es schon: Budget.pdf (Vorstand, 02.11.2026).",
      confirmLabel: "Bestehende anhängen",
      alternativeLabel: "Kopie hochladen",
    });
    expect(await screen.findByRole("link", { name: /Budget\.pdf/ })).toHaveAttribute("href", existing.content_url);
    expect(upload).not.toHaveBeenCalled();
  });

  it("Duplikat: «Kopie hochladen» lädt normal hoch, Abbrechen tut nichts", async () => {
    duplicateMatches = [{ sha256: "x", file: existing }];
    choice.mockResolvedValueOnce("cancel").mockResolvedValueOnce("alternative");
    mount();
    const shell = await dialogShell();
    fireEvent.drop(shell, fileTransfer([new File(["x"], "a.pdf"), new File(["x"], "b.pdf")]));

    await waitFor(() => expect(upload).toHaveBeenCalledOnce());
    expect(choice).toHaveBeenCalledTimes(2);
    expect(((upload.mock.calls[0][1] as FormData).get("files") as File).name).toBe("b.pdf");
  });

  it("meldet Fehler des Backends und hängt nichts an", async () => {
    upload.mockResolvedValue({ items: [], errors: ["virus.pdf: wurde von der Virenprüfung als infiziert erkannt"], file_results: [] });
    mount();
    const shell = await dialogShell();
    fireEvent.drop(shell, fileTransfer([new File(["x"], "virus.pdf")]));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringContaining("infiziert"), "error"));
    expect(screen.queryByRole("link", { name: /virus\.pdf/ })).toBeNull();
  });
});

describe("Dateisuche", () => {
  it("Escape schliesst nur die Trefferliste, nicht den Dialog", async () => {
    const onClose = vi.fn();
    mount({ onClose });
    const input = await screen.findByPlaceholderText("Hochgeladene Datei suchen …");
    input.focus();
    fireEvent.focus(input);
    expect(await screen.findByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
  });


  it("öffnet die Trefferliste als Portal ausserhalb des Feldes (Dialoghöhe bleibt)", async () => {
    const { container } = render(<TodoFilePicker excludeIds={[]} onPick={vi.fn()} onUploadFiles={vi.fn()} />);
    fireEvent.focus(screen.getByRole("combobox"));
    const listbox = await screen.findByRole("listbox");
    expect(container.contains(listbox)).toBe(false);
    expect(listbox.style.position).toBe("fixed");
    expect(await within(listbox).findByRole("option", { name: /Budget\.pdf/ })).toBeInTheDocument();
  });

  it("Tastatur: «Datei hochladen …» ist ein Eintrag der Liste und öffnet die Dateiauswahl", async () => {
    const onUploadFiles = vi.fn();
    render(<TodoFilePicker excludeIds={[]} onPick={vi.fn()} onUploadFiles={onUploadFiles} />);
    const input = screen.getByRole("combobox");
    const fileInput = screen.getByTestId("todo-file-upload-input") as HTMLInputElement;
    const click = vi.spyOn(fileInput, "click").mockImplementation(() => undefined);
    input.focus();
    fireEvent.focus(input);
    await screen.findByRole("option", { name: /Budget\.pdf/ });

    fireEvent.keyDown(input, { key: "ArrowUp" });
    const uploadOption = screen.getByRole("option", { name: "Datei hochladen …" });
    expect(input).toHaveAttribute("aria-activedescendant", uploadOption.id);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(click).toHaveBeenCalledOnce();
    expect(screen.queryByRole("listbox")).toBeNull();

    const file = new File(["x"], "a.pdf");
    await act(async () => { fireEvent.change(fileInput, { target: { files: [file] } }); });
    expect(onUploadFiles).toHaveBeenCalledWith([file]);
  });

  it("ohne Upload-Recht kein Upload-Eintrag", async () => {
    render(<TodoFilePicker excludeIds={[]} onPick={vi.fn()} />);
    fireEvent.focus(screen.getByRole("combobox"));
    await screen.findByRole("option", { name: /Budget\.pdf/ });
    expect(screen.queryByRole("option", { name: "Datei hochladen …" })).toBeNull();
  });
});
