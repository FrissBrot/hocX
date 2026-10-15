import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const browserApiUploadMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
  browserApiUpload: (...args: unknown[]) => browserApiUploadMock(...args),
}));

import { GalleryUploadModal } from "./gallery-upload-modal";

function fixture(name: string, as = name): File {
  const bytes = readFileSync(join(__dirname, "../../lib/image-analysis/__fixtures__", name));
  return new File([new Uint8Array(bytes)], as, { type: name.endsWith(".jpg") ? "image/jpeg" : "" });
}

type PrecheckBody = { estimated_taken_on: string | null; files: { client_id: string; sha256: string; metadata: unknown }[] };

function precheckBodies(): PrecheckBody[] {
  return browserApiFetchMock.mock.calls
    .filter(([url]) => url === "/api/files/upload-precheck")
    .map(([, init]) => JSON.parse((init as { body: string }).body));
}

function uploadedNames(): string[][] {
  return browserApiUploadMock.mock.calls.map(([, body]) => (body as FormData).getAll("files").map((file) => (file as File).name));
}

function renderModal(files: File[], extra: Partial<Parameters<typeof GalleryUploadModal>[0]> = {}) {
  const onClose = vi.fn();
  const onQueued = vi.fn();
  const onSessionComplete = vi.fn();
  render(
    <GalleryUploadModal tagSuggestions={[]} initialFiles={files} onClose={onClose} onQueued={onQueued} onSessionComplete={onSessionComplete} {...extra} />,
  );
  return { onClose, onQueued, onSessionComplete };
}

function mockPrecheck(status: (clientId: string, sha: string) => string, applied: string[] = []) {
  browserApiFetchMock.mockImplementation((url: string, init?: { body?: string }) => {
    if (url === "/api/files/upload-precheck") {
      const body = JSON.parse(init?.body ?? "{}") as PrecheckBody;
      return Promise.resolve({
        results: body.files.map((file) => ({
          client_id: file.client_id,
          status: status(file.client_id, file.sha256),
          file_id: "existing",
          applied: status(file.client_id, file.sha256) === "metadata_updated" ? applied : [],
          conflicts: [],
        })),
      });
    }
    return Promise.resolve([]);
  });
}

describe("GalleryUploadModal – Analyse, Schätzdatum und Vorab-Abgleich", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    browserApiUploadMock.mockReset();
    browserApiFetchMock.mockResolvedValue([]);
    browserApiUploadMock.mockImplementation(() => Promise.resolve({ id: `job-${browserApiUploadMock.mock.calls.length}`, status: "queued" }));
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("zeigt den Hinweis nur für Bilder ohne Aufnahmedatum und bietet das Schätzdatum an", async () => {
    renderModal([fixture("full.jpg", "mit.jpg"), fixture("plain.jpg", "ohne-1.jpg"), fixture("plain.jpg", "ohne-2.jpg")]);
    expect(await screen.findByText(/Für 2 Bilder wurde kein Aufnahmedatum gefunden/)).toBeInTheDocument();
    expect(screen.getByText("Geschätztes Aufnahmedatum für Bilder ohne Aufnahmedatum")).toBeInTheDocument();
    expect(screen.getAllByText("Bereit · kein Aufnahmedatum gefunden")).toHaveLength(2);
  });

  it("zeigt keinen Hinweis, wenn alle Bilder ein Aufnahmedatum haben", async () => {
    renderModal([fixture("full.jpg", "a.jpg")]);
    await waitFor(() => expect(screen.queryByText("Bilder werden geprüft…", { exact: false })).not.toBeInTheDocument());
    expect(screen.queryByText("Geschätztes Aufnahmedatum für Bilder ohne Aufnahmedatum")).not.toBeInTheDocument();
  });

  it("behandelt nicht prüfbare Bilder nicht als Bilder ohne Datum", async () => {
    renderModal([new File([new TextEncoder().encode("kein bekanntes Format")], "seltsam.jpg")]);
    expect(await screen.findByText(/1 Bild konnte im Browser nicht geprüft werden/)).toBeInTheDocument();
    expect(screen.queryByText(/wurde kein Aufnahmedatum gefunden/)).not.toBeInTheDocument();
  });

  it("überträgt vorhandene Bilder nicht und sendet Schätzdatum samt Metadaten mit", async () => {
    const known = fixture("plain.jpg", "schon-da.jpg");
    mockPrecheck((clientId) => (clientId === "0" ? "metadata_updated" : "upload_required"), ["estimated_taken_on"]);
    const { onClose, onSessionComplete, onQueued } = renderModal([known, fixture("full.jpg", "neu.jpg")]);
    await screen.findByText(/Für 1 Bild wurde kein Aufnahmedatum gefunden/);

    const input = document.querySelector(".gallery-upload-estimate input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "01.08.1998" } });
    fireEvent.blur(input);
    fireEvent.click(screen.getByRole("button", { name: "2 Bilder hochladen" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const [body] = precheckBodies();
    expect(body.estimated_taken_on).toBe("1998-08-01");
    expect(body.files).toHaveLength(2);
    expect(uploadedNames()).toEqual([["neu.jpg"]]);
    const form = browserApiUploadMock.mock.calls[0][1] as FormData;
    expect(form.get("estimated_taken_on")).toBe("1998-08-01");
    expect(JSON.parse(String(form.get("file_metadata")))[0].metadata.taken_at).toBe("2023-07-14T10:30:05");
    expect(onQueued).toHaveBeenCalledTimes(1);
    expect(onSessionComplete).toHaveBeenCalledWith({
      jobIds: ["job-1"],
      precheckResults: [{ name: "schon-da.jpg", status: "metadata_updated", file_id: "existing", applied: ["estimated_taken_on"], conflicts: [] }],
    });
  });

  it("lädt nichts hoch, wenn alle Bilder schon vorhanden sind", async () => {
    mockPrecheck(() => "already_exists");
    const { onSessionComplete, onClose } = renderModal([fixture("full.jpg", "a.jpg")]);
    await waitFor(() => expect(screen.queryByText("Bilder werden geprüft…", { exact: false })).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "1 Bild hochladen" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(browserApiUploadMock).not.toHaveBeenCalled();
    expect(onSessionComplete.mock.calls[0][0].precheckResults[0].status).toBe("skipped");
  });

  it("fällt bei einem Fehler des Vorab-Abgleichs auf den normalen Upload zurück", async () => {
    browserApiFetchMock.mockImplementation((url: string) => (url === "/api/files/upload-precheck" ? Promise.reject(new Error("down")) : Promise.resolve([])));
    const { onClose } = renderModal([fixture("full.jpg", "a.jpg"), fixture("plain.jpg", "b.jpg")]);
    await waitFor(() => expect(screen.queryByText("Bilder werden geprüft…", { exact: false })).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "2 Bilder hochladen" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(uploadedNames()).toEqual([["a.jpg", "b.jpg"]]);
  });

  it("teilt grosse Auswahlen automatisch in Aufträge zu höchstens 50 Dateien", async () => {
    mockPrecheck(() => "upload_required");
    const bytes = readFileSync(join(__dirname, "../../lib/image-analysis/__fixtures__", "plain.jpg"));
    const files = Array.from({ length: 120 }, (_, index) => {
      const copy = new Uint8Array(bytes.length + 1);
      copy.set(bytes);
      copy[bytes.length] = index; // eindeutiger Hash je Datei
      return new File([copy], `bild-${index}.jpg`, { type: "image/jpeg" });
    });
    const { onClose, onSessionComplete } = renderModal(files);
    await waitFor(() => expect(screen.queryByText("Bilder werden geprüft…", { exact: false })).not.toBeInTheDocument(), { timeout: 15000 });
    fireEvent.click(screen.getByRole("button", { name: "120 Bilder hochladen" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled(), { timeout: 15000 });
    expect(uploadedNames().map((names) => names.length)).toEqual([50, 50, 20]);
    expect(onSessionComplete.mock.calls[0][0].jobIds).toEqual(["job-1", "job-2", "job-3"]);
  }, 30000);

  it("zeigt bei ZIP-Dateien das Schätzdatum mit Server-Hinweis an und prüft sie nicht im Browser", async () => {
    renderModal([new File([new Uint8Array([0x50, 0x4b, 3, 4])], "album.zip", { type: "application/zip" })]);
    expect(await screen.findByText(/Bilder in ZIP-Dateien prüft der Server/)).toBeInTheDocument();
  });
});
