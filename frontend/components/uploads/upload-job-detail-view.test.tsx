import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();
const photosViewProps = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiBaseUrl: "", browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args) }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => showToastMock }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn() }));
vi.mock("@/components/photos/photos-view", () => ({
  PhotosView: (props: Record<string, unknown>) => {
    photosViewProps(props);
    return <div data-testid="photos-view" />;
  },
}));

import type { UploadJobDetail } from "@/types/api";

import { UploadJobDetailView } from "./upload-job-detail-view";

const detail: UploadJobDetail = {
  id: "job-1", channel: "gallery", actor_kind: "user", created_by_name: "Anna", created_by_deleted: false, is_mine: true,
  status: "done", reconstructed: false, created_at: "2026-11-21T10:00:00Z", finished_at: "2026-11-21T10:05:00Z",
  counts: { total: 3, uploaded: 2, duplicates: 1, metadata_updated: 0, rejected: 0, infected: 0, failed: 0, discarded: 0 },
  ref: null, image_count: 2, options: { tags: ["Lager"], include_gps: true }, import_job_id: null, file_count: 2,
  cameras: [{
    key: "k1", camera_make: "Canon", camera_model: "EOS R6", device_index: 2, count: 2, earliest: "2026-05-02T10:00:00Z",
    latest: "2026-05-02T11:00:00Z", with_time: 2, with_gps_time: 0, suggested_shift_minutes: -74, suggestion_samples: 3,
  }],
};

describe("UploadJobDetailView", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    photosViewProps.mockReset();
  });

  it("zeigt Kameras mit Vorschlag und wählt die Fotos einer Kamera im eingebetteten Raster", async () => {
    browserApiFetchMock.mockResolvedValue({ file_ids: ["f1", "f2"], total: 2, truncated: false });
    render(<UploadJobDetailView area="photos" job={detail} canManagePhotos canShare={false} canManageSettings={false} />);
    expect(screen.getByText("Canon EOS R6 (Gerät 2)")).toBeInTheDocument();
    expect(screen.getByText(/vermutlich: 1 h 14 min früher/)).toBeInTheDocument();
    expect(photosViewProps.mock.calls.at(-1)?.[0].uploadJobId).toBe("job-1");
    fireEvent.click(screen.getByRole("button", { name: "Nur diese auswählen" }));
    await waitFor(() => expect(photosViewProps.mock.calls.at(-1)?.[0].selectionRequest?.ids).toEqual(["f1", "f2"]));
    expect(browserApiFetchMock).toHaveBeenCalledWith("/api/upload-jobs/job-1/file-ids?only_images=true&camera=k1");
  });

  it("listet die Ergebnisse je Datei mit Zustand und Grund", async () => {
    browserApiFetchMock.mockResolvedValue({
      items: [
        { id: 1, position: 0, name: "a.jpg", status: "uploaded", reason_code: null, reason_params: {}, source: "server", size_bytes: 2048, mime_type: "image/jpeg", applied: [], file: { id: null, state: "trashed", is_image: true, thumbnail_url: null }, existing_file: null },
        { id: 2, position: 1, name: "riesig.jpg", status: "rejected", reason_code: "too_large", reason_params: {}, source: "client", size_bytes: null, mime_type: null, applied: [], file: null, existing_file: null },
      ],
      next_cursor: null,
    });
    render(<UploadJobDetailView area="photos" job={detail} canManagePhotos canShare={false} canManageSettings={false} />);
    fireEvent.click(screen.getByRole("tab", { name: /Ergebnisliste/ }));
    expect(await screen.findByText("Im Papierkorb")).toBeInTheDocument();
    expect(screen.getByText("Zu gross")).toBeInTheDocument();
    expect(screen.getByText("vom Browser gemeldet")).toBeInTheDocument();
  });

  it("macht eine Datumskorrektur rückgängig", async () => {
    browserApiFetchMock.mockImplementation((url: string) => {
      // Foto-Standorte: keine Ortsänderungen in diesem Vorgang
      if (url.startsWith("/api/place-changes?")) return Promise.resolve([]);
      if (url.startsWith("/api/capture-changes?")) {
        return Promise.resolve([{ id: "b1", mode: "shift", params: { shift_days: 0, shift_hours: -1, shift_minutes: -15 }, created_at: "2026-11-21T11:00:00Z", created_by_name: "Anna", updated_count: 2, remaining: 2, undone_at: null, can_undo: true }]);
      }
      return Promise.resolve({ restored_ids: ["f1", "f2"], conflict_ids: [], not_found_ids: [] });
    });
    render(<UploadJobDetailView area="photos" job={detail} canManagePhotos canShare={false} canManageSettings={false} />);
    fireEvent.click(screen.getByRole("tab", { name: "Datumskorrekturen" }));
    expect(await screen.findByText("Verschoben: 1 h 15 min früher")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rückgängig machen" }));
    await waitFor(() => expect(showToastMock).toHaveBeenCalledWith("2 Fotos zurückgesetzt.", "success"));
  });

  it("zeigt bei Dokumenten nur die Ergebnisliste", () => {
    browserApiFetchMock.mockResolvedValue({ items: [], next_cursor: null });
    render(<UploadJobDetailView area="files" job={{ ...detail, channel: "document", image_count: 0, cameras: [] }} canManagePhotos canShare={false} canManageSettings={false} />);
    expect(screen.queryByRole("tab", { name: "Fotos" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Ergebnisliste/ })).toHaveAttribute("aria-selected", "true");
  });
});
