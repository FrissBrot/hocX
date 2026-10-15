import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentDetail, FileOverviewItem } from "@/types/api";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

vi.mock("@/contexts/toast-context", () => ({
  useToast: () => showToastMock,
}));

import { FileDetailModal } from "./file-detail-modal";
import { FilesTable } from "./files-table";

const DOC_ID = "doc-1";

function makeItem(overrides: Partial<FileOverviewItem> = {}): FileOverviewItem {
  return {
    id: "file-1",
    original_name: "bericht.docx",
    mime_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    file_size_bytes: 2048,
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
    tags: [],
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
    document: {
      id: DOC_ID,
      status: "ready",
      pdf_status: "done",
      extraction_status: "ready",
      pdf_url: `/api/documents/${DOC_ID}/versions/v2/files/pdf`,
      pdf_download_url: `/api/documents/${DOC_ID}/versions/v2/files/pdf?download=1`,
      version_count: 2,
      current_version_number: 2,
      current_version_label: "v0.1",
      detail_url: `/api/documents/${DOC_ID}`,
    },
    ...overrides,
  } as FileOverviewItem;
}

function makeDetail(overrides: Partial<DocumentDetail> = {}): DocumentDetail {
  const file = (version: string, role: string, name: string, mime: string) => ({
    name,
    mime_type: mime,
    size_bytes: 100,
    url: `/api/documents/${DOC_ID}/versions/${version}/files/${role}`,
    download_url: `/api/documents/${DOC_ID}/versions/${version}/files/${role}?download=1`,
  });
  const docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  return {
    id: DOC_ID,
    display_name: "bericht.docx",
    source_kind: "upload",
    status: "ready",
    created_at: "2026-10-01T10:00:00Z",
    updated_at: "2026-10-02T10:00:00Z",
    current_version_id: "v2",
    can_reprocess: false,
    versions: [
      {
        id: "v2", version_number: 2, label: "v0.1", created_at: "2026-10-02T10:00:00Z", is_current: true,
        original: file("v2", "original", "bericht.docx", docx), pdf: file("v2", "pdf", "bericht.pdf", "application/pdf"),
        pdf_job: { status: "done", result: "converted", attempts: 1 }, extract_job: { status: "done", result: "extracted", attempts: 1 },
        extraction: {
          status: "ready", parser: "docx", parser_version: "1", schema_version: 1, page_count: null, char_count: 20,
          ocr_applied: false, warnings: [], error: null, text_url: `/api/documents/${DOC_ID}/versions/v2/text`,
        },
      },
      {
        id: "v1", version_number: 1, label: null, created_at: "2026-10-01T10:00:00Z", is_current: false,
        original: file("v1", "original", "bericht.docx", docx), pdf: file("v1", "pdf", "bericht.pdf", "application/pdf"),
        pdf_job: { status: "done", result: "converted", attempts: 1 }, extract_job: { status: "done", result: "extracted", attempts: 1 },
        extraction: null,
      },
    ],
    ...overrides,
  };
}

describe("Dokumente im Dateien-Tab", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
  });

  it("zeigt einen Eintrag mit PDF-Link, Versionskennung und ohne Status bei fertigen Dokumenten", () => {
    render(<FilesTable items={[makeItem()]} onOpenDetail={() => {}} onNavigate={() => {}} onShare={() => {}} />);
    const link = screen.getByRole("link", { name: "PDF öffnen" }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe(`/api/documents/${DOC_ID}/versions/v2/files/pdf`);
    expect(screen.getByText("v0.1")).toBeInTheDocument();
    expect(screen.queryByText("In Verarbeitung")).not.toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(2); // Kopfzeile + genau ein Dokument
  });

  it("zeigt den Verarbeitungsstatus, solange noch kein PDF da ist", () => {
    const item = makeItem({
      document: { ...makeItem().document!, status: "processing", pdf_status: "queued", pdf_url: null, pdf_download_url: null, version_count: 1 },
    });
    render(<FilesTable items={[item]} onOpenDetail={() => {}} onNavigate={() => {}} onShare={() => {}} />);
    expect(screen.getByText("In Verarbeitung")).toBeInTheDocument();
    expect((screen.getByRole("link", { name: "Download" }) as HTMLAnchorElement).getAttribute("href")).toBe("/api/stored-files/file-1/content");
  });

  it("zeigt im Detaildialog die PDF-Vorschau, Original-Download, Text und Versionshistorie", async () => {
    browserApiFetchMock.mockImplementation(async (url: string) => {
      if (url === `/api/documents/${DOC_ID}`) return makeDetail();
      if (url.endsWith("/text?format=plain")) return { format: "plain", status: "ready", text: "Jahresbericht\n\nInhalt", content: null };
      return null;
    });
    render(
      <FileDetailModal item={makeItem()} tagSuggestions={[]} onClose={() => {}} onNavigate={() => {}} onTagsSaved={() => {}} />
    );

    const preview = (await screen.findByTitle("PDF-Vorschau von bericht.docx")) as HTMLIFrameElement;
    expect(preview.getAttribute("src")).toBe(`/api/documents/${DOC_ID}/versions/v2/files/pdf`);
    expect((screen.getByRole("link", { name: "Originaldatei herunterladen" }) as HTMLAnchorElement).getAttribute("href")).toContain(
      "/versions/v2/files/original?download=1"
    );
    expect(screen.getByText("Versionen (2)")).toBeInTheDocument();
    expect(screen.getByText("Version 1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Extrahierten Text anzeigen" }));
    await waitFor(() => expect(screen.getByLabelText("Text")).toHaveTextContent("Jahresbericht"));
  });

  it("bietet erneute Verarbeitung nur an, wenn sie erlaubt und nötig ist", async () => {
    browserApiFetchMock.mockImplementation(async (url: string) => {
      if (url === `/api/documents/${DOC_ID}`) return makeDetail({ status: "partial", can_reprocess: true });
      return { requeued: 1 };
    });
    render(
      <FileDetailModal item={makeItem()} tagSuggestions={[]} onClose={() => {}} onNavigate={() => {}} onTagsSaved={() => {}} />
    );
    fireEvent.click(await screen.findByRole("button", { name: "Erneut verarbeiten" }));
    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith(`/api/documents/${DOC_ID}/reprocess`, { method: "POST" }));
    expect(showToastMock).toHaveBeenCalledWith("Verarbeitung wurde neu gestartet.", "success");
  });
});
