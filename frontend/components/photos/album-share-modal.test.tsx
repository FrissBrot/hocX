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
import { AlbumTenantShareStatus, PhotoAlbum, TenantLookup } from "@/types/api";

const TENANT_ID = "01a0b7e9-c62b-7044-b081-78169c5e02e3";

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
    is_shared: false,
    pending_share_count: 0,
    ...overrides,
  };
}

function anonymous(id = TENANT_ID): TenantLookup {
  return { id, trusted: false, name: null, slug: null, participant_count: null, profile_image_url: null };
}

function trusted(overrides: Partial<TenantLookup> = {}): TenantLookup {
  return {
    id: TENANT_ID,
    trusted: true,
    name: "Jubla Sonnenberg",
    slug: "jubla-sonnenberg",
    participant_count: 48,
    profile_image_url: `/api/tenants/${TENANT_ID}/profile-image`,
    ...overrides,
  };
}

function share(overrides: Partial<AlbumTenantShareStatus> = {}): AlbumTenantShareStatus {
  return {
    tenant_public_id: "partner-1",
    tenant_name: "Pfadi Wildegg",
    tenant_profile_image_url: null,
    status: "accepted",
    invited_at: "2026-09-10T08:00:00Z",
    responded_at: "2026-09-12T08:00:00Z",
    ...overrides,
  };
}

function typeInto(value: string) {
  fireEvent.change(screen.getByPlaceholderText("Mandanten-ID einfügen"), { target: { value } });
}

describe("AlbumShareModal", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    confirmMock.mockReset();
  });

  it("shows only an anonymous match for a pasted id without trust", async () => {
    browserApiFetchMock.mockResolvedValue(anonymous());

    render(<AlbumShareModal open album={makeAlbum()} onClose={() => {}} onChanged={() => {}} />);
    typeInto(TENANT_ID);

    expect(await screen.findByText("Mandant gefunden")).toBeTruthy();
    expect(browserApiFetchMock).toHaveBeenCalledWith(`/api/tenants/lookup?public_id=${TENANT_ID}`);
    expect(screen.getByTestId("tenant-avatar-generic")).toBeTruthy();
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByRole("button", { name: "Einladen" })).toBeEnabled();
  });

  it("shows name, details and profile image for a trusted tenant", async () => {
    browserApiFetchMock.mockResolvedValue(trusted());

    render(<AlbumShareModal open album={makeAlbum()} onClose={() => {}} onChanged={() => {}} />);
    typeInto(TENANT_ID);

    expect(await screen.findByText("Jubla Sonnenberg")).toBeTruthy();
    expect(screen.getByText("jubla-sonnenberg · 48 Teilnehmer")).toBeTruthy();
    expect(document.querySelector(".album-share-found img")?.getAttribute("src")).toBe(`/api/tenants/${TENANT_ID}/profile-image`);
    expect(screen.getByRole("button", { name: "Jubla Sonnenberg einladen" })).toBeEnabled();
  });

  it("searches names only among trusted tenants and lets one be picked", async () => {
    browserApiFetchMock.mockResolvedValue([trusted()]);

    render(<AlbumShareModal open album={makeAlbum()} onClose={() => {}} onChanged={() => {}} />);
    typeInto("jubla");

    fireEvent.click(await screen.findByRole("button", { name: /Jubla Sonnenberg/ }));

    expect(browserApiFetchMock).toHaveBeenCalledWith("/api/tenants/trusted?search=jubla");
    expect(browserApiFetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/api/tenants/lookup"));
    expect(await screen.findByText("✓ Gefunden")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Jubla Sonnenberg einladen" })).toBeEnabled();
  });

  it("explains that unknown tenants are only found by id", async () => {
    browserApiFetchMock.mockResolvedValue([]);

    render(<AlbumShareModal open album={makeAlbum()} onClose={() => {}} onChanged={() => {}} />);
    typeInto("Geheimer Verein");

    expect(await screen.findByText(/Neue Mandanten findest du nur über ihre Mandanten-ID/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Einladen" })).toBeDisabled();
  });

  it("shows an error and keeps invite disabled when no tenant has the id", async () => {
    browserApiFetchMock.mockRejectedValue(new Error("404"));

    render(<AlbumShareModal open album={makeAlbum()} onClose={() => {}} onChanged={() => {}} />);
    typeInto(TENANT_ID);

    expect(await screen.findByText("Kein Mandant mit dieser ID gefunden.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Einladen" })).toBeDisabled();
  });

  it("invites an anonymous tenant without ever naming it", async () => {
    browserApiFetchMock.mockResolvedValueOnce(anonymous());
    browserApiFetchMock.mockResolvedValueOnce(undefined);
    const onChanged = vi.fn();

    render(<AlbumShareModal open album={makeAlbum()} onClose={() => {}} onChanged={onChanged} />);
    typeInto(TENANT_ID);
    await screen.findByText("Mandant gefunden");

    fireEvent.click(screen.getByRole("button", { name: "Einladen" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    const [path, init] = browserApiFetchMock.mock.calls[1];
    expect(path).toBe("/api/files/albums/album-1/shares");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ target_tenant_public_id: TENANT_ID });
    expect(showToastMock).toHaveBeenCalledWith("Einladung gesendet.", "success");
  });

  it("lists a pending invite to an untrusted tenant anonymously", () => {
    const album = makeAlbum({
      shared_with: [share({ tenant_public_id: TENANT_ID, tenant_name: null, status: "pending", responded_at: null })],
    });

    render(<AlbumShareModal open album={album} onClose={() => {}} onChanged={() => {}} />);

    expect(screen.getByText("Unbekannter Mandant")).toBeTruthy();
    expect(screen.getByText("01a0b7e9…")).toBeTruthy();
    expect(screen.getByText("Einladung offen")).toBeTruthy();
    expect(screen.getByTestId("tenant-avatar-generic")).toBeTruthy();
  });

  it("lists a trusted share with name and revokes it on confirm", async () => {
    confirmMock.mockResolvedValue(true);
    browserApiFetchMock.mockResolvedValue(undefined);
    const onChanged = vi.fn();

    render(<AlbumShareModal open album={makeAlbum({ shared_with: [share()] })} onClose={() => {}} onChanged={onChanged} />);

    expect(screen.getByText("Pfadi Wildegg")).toBeTruthy();
    expect(screen.getByText("Hat Zugriff")).toBeTruthy();
    expect(screen.getByText(/^seit 12\. Sept?\. 2026$/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Freigabe für Pfadi Wildegg entfernen" }));

    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith("/api/files/albums/album-1/shares/partner-1", { method: "DELETE" }));
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("does not revoke when the confirmation is declined", async () => {
    confirmMock.mockResolvedValue(false);
    const album = makeAlbum({ shared_with: [share({ status: "pending", responded_at: null })] });

    render(<AlbumShareModal open album={album} onClose={() => {}} onChanged={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Einladung an Pfadi Wildegg zurückziehen" }));

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(browserApiFetchMock).not.toHaveBeenCalled();
  });
});
