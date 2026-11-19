import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();
const confirmMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

vi.mock("@/contexts/toast-context", () => ({
  useToast: () => showToastMock,
}));

vi.mock("@/contexts/confirm-context", () => ({
  useConfirm: () => confirmMock,
}));

import { TrashModal } from "./trash-modal";

const item = {
  id: "f1",
  original_name: "lager.jpg",
  mime_type: "image/jpeg",
  file_size_bytes: 2048,
  is_image: true,
  thumbnail_url: "/api/files/trash/f1/thumbnail",
  deleted_at: "2026-11-19T10:00:00Z",
  deleted_by_name: "Anna Muster",
  purge_at: "2026-12-19T10:00:00Z",
  days_left: 30,
};

function mockTrash(items = [item]) {
  browserApiFetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (url === "/api/files/trash" && !init) return Promise.resolve({ items, total_bytes: 2048, retention_days: 30 });
    if (url === "/api/files/trash/restore" || url === "/api/files/trash/purge") {
      return Promise.resolve({ file_ids: JSON.parse(String(init?.body)).file_ids, errors: [] });
    }
    if (url === "/api/files/trash/empty") return Promise.resolve({ purged: items.length });
    return Promise.resolve(null);
  });
}

describe("TrashModal", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    confirmMock.mockReset();
  });

  it("lists name, deletion date, who deleted it and the remaining days with a quota hint", async () => {
    mockTrash();
    render(<TrashModal open onClose={() => {}} />);

    expect(await screen.findByText("lager.jpg")).toBeTruthy();
    expect(screen.getByText("von Anna Muster")).toBeTruthy();
    expect(screen.getByText("Noch 30 Tage")).toBeTruthy();
    expect(screen.getByText(/zählen zum Speicherkontingent/)).toBeTruthy();
  });

  it("restores without asking and tells the page which files came back", async () => {
    mockTrash();
    const onRestored = vi.fn();
    render(<TrashModal open onClose={() => {}} onRestored={onRestored} />);

    fireEvent.click(await screen.findByRole("button", { name: "Wiederherstellen" }));

    await waitFor(() => expect(onRestored).toHaveBeenCalledWith(["f1"]));
    expect(confirmMock).not.toHaveBeenCalled();
    expect(browserApiFetchMock).toHaveBeenCalledWith("/api/files/trash/restore", { method: "POST", body: JSON.stringify({ file_ids: ["f1"] }) });
  });

  it("asks with tone danger before deleting permanently and does nothing when cancelled", async () => {
    mockTrash();
    confirmMock.mockResolvedValueOnce(false);
    render(<TrashModal open onClose={() => {}} />);

    fireEvent.click(await screen.findByRole("button", { name: "Endgültig löschen" }));

    await waitFor(() => expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({ tone: "danger" })));
    expect(browserApiFetchMock).not.toHaveBeenCalledWith("/api/files/trash/purge", expect.anything());
  });

  it("empties the trash after a danger confirmation", async () => {
    mockTrash();
    confirmMock.mockResolvedValueOnce(true);
    render(<TrashModal open onClose={() => {}} />);

    fireEvent.click(await screen.findByRole("button", { name: "Papierkorb leeren" }));

    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith("/api/files/trash/empty", { method: "POST" }));
    expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({ tone: "danger" }));
  });

  it("shows the empty state and disables emptying when nothing is in the trash", async () => {
    mockTrash([]);
    render(<TrashModal open onClose={() => {}} />);

    expect(await screen.findByText("Der Papierkorb ist leer.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Papierkorb leeren" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
