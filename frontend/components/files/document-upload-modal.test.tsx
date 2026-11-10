import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentUploadResult } from "@/types/api";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

import { DocumentUploadModal } from "./document-upload-modal";

function pdf(name = "protokoll.pdf") {
  return new File(["%PDF-1.7"], name, { type: "application/pdf" });
}

function addFiles(files: File[]) {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files } });
}

function uploadCalls() {
  return browserApiFetchMock.mock.calls.filter(([url]) => url === "/api/files/document-uploads");
}

describe("DocumentUploadModal", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("only accepts document formats in the file picker", () => {
    render(<DocumentUploadModal tagSuggestions={[]} onClose={() => {}} onUploaded={() => {}} />);

    const accept = (document.querySelector('input[type="file"]') as HTMLInputElement).accept;
    expect(accept).toContain(".pdf");
    expect(accept).toContain(".docx");
    expect(accept).not.toContain(".png");
  });

  it("queues chosen documents and disables the upload button until there is one", () => {
    render(<DocumentUploadModal tagSuggestions={[]} onClose={() => {}} onUploaded={() => {}} />);
    expect(screen.getByRole("button", { name: "Hochladen" })).toBeDisabled();

    addFiles([pdf("a.pdf"), pdf("b.pdf")]);

    expect(screen.getByText("a.pdf")).toBeInTheDocument();
    expect(screen.getByText("2 Dateien gewählt")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2 Dateien hochladen" })).toBeEnabled();
  });

  it("points images to the Fotos page instead of queueing them", () => {
    render(<DocumentUploadModal tagSuggestions={[]} onClose={() => {}} onUploaded={() => {}} />);

    addFiles([new File(["x"], "strand.png", { type: "image/png" })]);

    expect(screen.getByText("Bilder bitte über die Fotos-Seite hochladen.")).toBeInTheDocument();
    expect(screen.getByText("Keine Datei gewählt")).toBeInTheDocument();
  });

  it("posts the queue with tags as multipart form data, then reports the result and closes", async () => {
    const result: DocumentUploadResult = { items: [], errors: [] };
    result.items = [{ id: "f1", tags: ["Lager"] } as DocumentUploadResult["items"][number]];
    browserApiFetchMock.mockImplementation((url: string) =>
      Promise.resolve(url === "/api/files/document-uploads" ? result : []),
    );
    const onUploaded = vi.fn();
    const onClose = vi.fn();
    render(<DocumentUploadModal tagSuggestions={[]} onClose={onClose} onUploaded={onUploaded} />);

    addFiles([pdf()]);
    fireEvent.click(screen.getByRole("button", { name: "1 Datei hochladen" }));

    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(result));
    expect(onClose).toHaveBeenCalled();
    const [, init] = uploadCalls()[0] as [string, { method: string; body: FormData }];
    expect(init.method).toBe("POST");
    expect((init.body.getAll("files")[0] as File).name).toBe("protokoll.pdf");
    expect(init.body.has("event_id")).toBe(false);
  });

  it("stays open and shows the reasons when nothing could be saved", async () => {
    browserApiFetchMock.mockImplementation((url: string) =>
      Promise.resolve(url === "/api/files/document-uploads" ? { items: [], errors: ["a.pdf: wurde als infiziert erkannt"] } : []),
    );
    const onUploaded = vi.fn();
    const onClose = vi.fn();
    render(<DocumentUploadModal tagSuggestions={[]} onClose={onClose} onUploaded={onUploaded} />);

    addFiles([pdf("a.pdf")]);
    fireEvent.click(screen.getByRole("button", { name: "1 Datei hochladen" }));

    expect(await screen.findByText("a.pdf: wurde als infiziert erkannt")).toBeInTheDocument();
    expect(onUploaded).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does not transfer documents the server already has and reports them as skipped", async () => {
    browserApiFetchMock.mockImplementation((url: string, init?: { body?: string }) => {
      if (url === "/api/files/upload-precheck") {
        const files = JSON.parse(init?.body ?? "{}").files as { client_id: string }[];
        return Promise.resolve({
          results: files.map((file) => ({ client_id: file.client_id, status: "already_exists", file_id: "known", applied: [], conflicts: [] })),
        });
      }
      return Promise.resolve([]);
    });
    const onUploaded = vi.fn();
    const onClose = vi.fn();
    render(<DocumentUploadModal tagSuggestions={[]} onClose={onClose} onUploaded={onUploaded} />);

    addFiles([pdf("schon-da.pdf")]);
    fireEvent.click(screen.getByRole("button", { name: "1 Datei hochladen" }));

    await waitFor(() => expect(onUploaded).toHaveBeenCalled());
    expect(uploadCalls()).toHaveLength(0);
    expect(onUploaded.mock.calls[0][0].file_results).toEqual([
      { name: "schon-da.pdf", status: "skipped", file_id: "known", applied: [], conflicts: [] },
    ]);
    expect(onClose).toHaveBeenCalled();
  });

  it("falls back to the normal upload when the precheck fails", async () => {
    const result: DocumentUploadResult = { items: [{ id: "f1", tags: [] } as unknown as DocumentUploadResult["items"][number]], errors: [] };
    browserApiFetchMock.mockImplementation((url: string) =>
      url === "/api/files/upload-precheck" ? Promise.reject(new Error("offline")) : Promise.resolve(url === "/api/files/document-uploads" ? result : []),
    );
    const onUploaded = vi.fn();
    render(<DocumentUploadModal tagSuggestions={[]} onClose={() => {}} onUploaded={onUploaded} />);

    addFiles([pdf()]);
    fireEvent.click(screen.getByRole("button", { name: "1 Datei hochladen" }));

    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(result));
    expect(uploadCalls()).toHaveLength(1);
  });
});
