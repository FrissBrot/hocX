import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

vi.mock("@/contexts/toast-context", () => ({
  useToast: () => showToastMock,
}));

import { ShareLinkModal } from "./share-link-modal";
import { ShareLink } from "@/types/api";

function makeLink(overrides: Partial<ShareLink> = {}): ShareLink {
  return {
    id: "link-1",
    name: "Zwei Fotos",
    url: "/share/tok-abc123",
    album_name: null,
    file_count: 2,
    created_at: "2026-09-24T10:00:00Z",
    created_by_name: "Test User",
    expires_at: null,
    revoked_at: null,
    status: "active",
    ...overrides,
  };
}

describe("ShareLinkModal", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
  });

  it("creates a share link for the given file selection and shows the full URL", async () => {
    browserApiFetchMock.mockResolvedValue(makeLink());
    const onCreated = vi.fn();

    render(<ShareLinkModal open onClose={() => {}} fileIds={["file-1", "file-2"]} defaultName="2 Fotos" onCreated={onCreated} />);

    fireEvent.click(screen.getByRole("button", { name: "Link erstellen" }));

    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledTimes(1));
    const [path, init] = browserApiFetchMock.mock.calls[0];
    expect(path).toBe("/api/share-links");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toMatchObject({ name: "2 Fotos", file_ids: ["file-1", "file-2"], album_id: null });

    expect(await screen.findByText(`${window.location.origin}/share/tok-abc123`)).toBeTruthy();
    expect(onCreated).toHaveBeenCalledTimes(1);
  });

  it("creates an album share link with album_id instead of file_ids", async () => {
    browserApiFetchMock.mockResolvedValue(makeLink({ album_name: "Sommerlager" }));

    render(<ShareLinkModal open onClose={() => {}} albumId="album-1" defaultName="Sommerlager" />);

    fireEvent.click(screen.getByRole("button", { name: "Link erstellen" }));

    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledTimes(1));
    const body = JSON.parse((browserApiFetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body).toMatchObject({ album_id: "album-1", file_ids: null });
  });

  it("shows an error toast and stays on the form when creation fails", async () => {
    browserApiFetchMock.mockRejectedValue(new Error("Server sagt nein"));

    render(<ShareLinkModal open onClose={() => {}} fileIds={["file-1"]} defaultName="1 Foto" />);

    fireEvent.click(screen.getByRole("button", { name: "Link erstellen" }));

    await waitFor(() => expect(showToastMock).toHaveBeenCalledWith("Server sagt nein", "error"));
    expect(screen.getByRole("button", { name: "Link erstellen" })).toBeTruthy();
  });

  it("resets to the form state when reopened after closing", async () => {
    browserApiFetchMock.mockResolvedValue(makeLink());
    const onClose = vi.fn();

    render(<ShareLinkModal open onClose={onClose} fileIds={["file-1"]} defaultName="1 Foto" />);
    fireEvent.click(screen.getByRole("button", { name: "Link erstellen" }));
    await screen.findByRole("button", { name: "Fertig" });

    fireEvent.click(screen.getByRole("button", { name: "Fertig" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
