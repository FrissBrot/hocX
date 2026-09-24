import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();
const confirmMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

vi.mock("@/contexts/toast-context", () => ({
  useToast: () => showToastMock,
}));

vi.mock("@/contexts/confirm-context", () => ({
  useConfirm: () => confirmMock,
}));

import { AlbumShareModal } from "./album-share-modal";
import { PhotoAlbum } from "@/types/api";

function makeAlbum(overrides: Partial<PhotoAlbum> = {}): PhotoAlbum {
  return {
    id: "album-1",
    name: "Sommerlager",
    kind: "manual",
    photo_count: 3,
    best_of_count: 1,
    cover_thumbnail_urls: [],
    owner_tenant_name: null,
    shared_with: [],
    ...overrides,
  };
}

describe("AlbumShareModal", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    confirmMock.mockReset();
  });

  it("looks up the tenant by public_id on blur and shows the found name", async () => {
    browserApiFetchMock.mockResolvedValue({ id: "tenant-public-id", name: "Nachbarverein", slug: "nachbarverein", participant_count: 48 });

    render(<AlbumShareModal open album={makeAlbum()} onClose={() => {}} onChanged={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText("Mandanten-ID einfügen"), { target: { value: "tenant-public-id" } });
    fireEvent.blur(screen.getByPlaceholderText("Mandanten-ID einfügen"));

    expect(await screen.findByText("✓ Gefunden")).toBeTruthy();
    expect(screen.getByText("Nachbarverein")).toBeTruthy();
    expect(screen.getByText("nachbarverein · 48 Teilnehmer")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Nachbarverein einladen" })).toBeEnabled();
    expect(browserApiFetchMock).toHaveBeenCalledWith("/api/tenants/lookup?public_id=tenant-public-id");
  });

  it("shows an error and keeps invite disabled when no tenant is found", async () => {
    browserApiFetchMock.mockRejectedValue(new Error("404"));

    render(<AlbumShareModal open album={makeAlbum()} onClose={() => {}} onChanged={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText("Mandanten-ID einfügen"), { target: { value: "unknown" } });
    fireEvent.blur(screen.getByPlaceholderText("Mandanten-ID einfügen"));

    expect(await screen.findByText("Kein Mandant mit dieser ID gefunden.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Einladen" })).toBeDisabled();
  });

  it("resolves a pasted full tenant id right away and clears it again", async () => {
    browserApiFetchMock.mockResolvedValue({ id: "01a0b7e9-c62b-7044-b081-78169c5e02e3", name: "Jubla Sonnenberg", slug: "jubla-sonnenberg", participant_count: 48 });

    render(<AlbumShareModal open album={makeAlbum()} onClose={() => {}} onChanged={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText("Mandanten-ID einfügen"), { target: { value: "01a0b7e9-c62b-7044-b081-78169c5e02e3" } });

    expect(await screen.findByText("Jubla Sonnenberg")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Eingabe leeren" }));
    expect(screen.queryByText("Jubla Sonnenberg")).toBeNull();
    expect(screen.getByRole("button", { name: "Einladen" })).toBeDisabled();
  });

  it("invites the found tenant and reports the change", async () => {
    browserApiFetchMock.mockResolvedValueOnce({ id: "tenant-public-id", name: "Nachbarverein", slug: null, participant_count: 0 });
    browserApiFetchMock.mockResolvedValueOnce(undefined);
    const onChanged = vi.fn();

    render(<AlbumShareModal open album={makeAlbum()} onClose={() => {}} onChanged={onChanged} />);
    fireEvent.change(screen.getByPlaceholderText("Mandanten-ID einfügen"), { target: { value: "tenant-public-id" } });
    fireEvent.blur(screen.getByPlaceholderText("Mandanten-ID einfügen"));
    await screen.findByText("✓ Gefunden");

    fireEvent.click(screen.getByRole("button", { name: "Nachbarverein einladen" }));

    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledTimes(2));
    const [path, init] = browserApiFetchMock.mock.calls[1];
    expect(path).toBe("/api/files/albums/album-1/shares");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ target_tenant_public_id: "tenant-public-id" });
    expect(showToastMock).toHaveBeenCalledWith("Einladung an Nachbarverein gesendet.", "success");
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("lists existing shares with their status and revokes on confirm", async () => {
    confirmMock.mockResolvedValue(true);
    browserApiFetchMock.mockResolvedValue(undefined);
    const onChanged = vi.fn();
    const album = makeAlbum({
      shared_with: [{ tenant_public_id: "partner-1", tenant_name: "Nachbarverein", status: "accepted", invited_at: "2026-09-10T08:00:00Z", responded_at: "2026-09-12T08:00:00Z" }],
    });

    render(<AlbumShareModal open album={album} onClose={() => {}} onChanged={onChanged} />);

    expect(screen.getByText("Nachbarverein")).toBeTruthy();
    expect(screen.getByText("Hat Zugriff")).toBeTruthy();
    expect(screen.getByText(/^seit 12\. Sept?\. 2026$/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Freigabe für Nachbarverein entfernen" }));

    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith("/api/files/albums/album-1/shares/partner-1", { method: "DELETE" }));
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("does not revoke when the confirmation is declined", async () => {
    confirmMock.mockResolvedValue(false);
    const album = makeAlbum({
      shared_with: [{ tenant_public_id: "partner-1", tenant_name: "Nachbarverein", status: "pending", invited_at: "2026-09-21T08:00:00Z", responded_at: null }],
    });

    render(<AlbumShareModal open album={album} onClose={() => {}} onChanged={() => {}} />);
    expect(screen.getByText("Einladung offen")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Einladung an Nachbarverein zurückziehen" }));

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(browserApiFetchMock).not.toHaveBeenCalled();
  });
});
