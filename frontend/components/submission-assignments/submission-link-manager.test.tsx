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

import { SubmissionLinkManager } from "./submission-link-manager";
import { SubmissionLink } from "@/types/api";

const link = (overrides: Partial<SubmissionLink> = {}): SubmissionLink => ({
  id: "link-1",
  name: "Standard",
  is_default: true,
  token: "tok-standard",
  url: "https://upload.example.com/tok-standard",
  assignment_count: 2,
  created_at: "2026-09-19T10:00:00Z",
  ...overrides,
});

describe("SubmissionLinkManager", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    confirmMock.mockReset();
  });

  it("shows each link by its clear name, marks the default and shows the full random URL", () => {
    render(
      <SubmissionLinkManager
        links={[link(), link({ id: "link-2", name: "Eltern", is_default: false, url: "https://upload.example.com/tok-eltern" })]}
        onLinksChange={() => {}}
        onLinkRemoved={() => {}}
      />
    );

    expect(screen.getByText("Eltern")).toBeTruthy();
    expect(screen.getAllByText("Standard").length).toBe(2); // name + default badge
    expect(screen.getByText("https://upload.example.com/tok-eltern")).toBeTruthy();
    expect(screen.getAllByText("2 Abgaben").length).toBe(2);
  });

  it("creates a link from just a name - the token is generated server-side", async () => {
    const created = link({ id: "link-3", name: "Leiterteam", is_default: false, url: "https://upload.example.com/tok-3" });
    browserApiFetchMock.mockResolvedValue(created);
    const onLinksChange = vi.fn();

    render(<SubmissionLinkManager links={[link()]} onLinksChange={onLinksChange} onLinkRemoved={() => {}} />);

    fireEvent.change(screen.getByPlaceholderText(/Name, z\. B\./), { target: { value: "Leiterteam" } });
    fireEvent.click(screen.getByRole("button", { name: "Link erstellen" }));

    await waitFor(() => expect(onLinksChange).toHaveBeenCalledWith([link(), created]));
    const [url, init] = browserApiFetchMock.mock.calls[0];
    expect(url).toBe("/api/submission-links");
    expect(JSON.parse(init.body)).toEqual({ name: "Leiterteam", is_default: false });
  });

  it("does not delete without confirmation", async () => {
    confirmMock.mockResolvedValue(false);
    const onLinkRemoved = vi.fn();

    render(<SubmissionLinkManager links={[link()]} onLinksChange={() => {}} onLinkRemoved={onLinkRemoved} />);
    fireEvent.click(screen.getByRole("button", { name: "Löschen" }));

    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    expect(browserApiFetchMock).not.toHaveBeenCalled();
    expect(onLinkRemoved).not.toHaveBeenCalled();
  });

  it("warns about affected Abgaben, then deletes and tells the parent", async () => {
    confirmMock.mockResolvedValue(true);
    browserApiFetchMock.mockResolvedValue({ message: "Link geloescht" });
    const onLinksChange = vi.fn();
    const onLinkRemoved = vi.fn();

    render(<SubmissionLinkManager links={[link()]} onLinksChange={onLinksChange} onLinkRemoved={onLinkRemoved} />);
    fireEvent.click(screen.getByRole("button", { name: "Löschen" }));

    await waitFor(() => expect(onLinkRemoved).toHaveBeenCalledWith("link-1"));
    expect(confirmMock.mock.calls[0][0].message).toContain("2 Abgaben sind darüber erreichbar");
    expect(browserApiFetchMock).toHaveBeenCalledWith("/api/submission-links/link-1", { method: "DELETE" });
    expect(onLinksChange).toHaveBeenCalledWith([]);
  });

  it("keeps a single default link after making another one the default", async () => {
    const other = link({ id: "link-2", name: "Eltern", is_default: false });
    browserApiFetchMock.mockResolvedValue({ ...other, is_default: true });
    const onLinksChange = vi.fn();

    render(<SubmissionLinkManager links={[link(), other]} onLinksChange={onLinksChange} onLinkRemoved={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Als Standard festlegen" }));

    await waitFor(() => expect(onLinksChange).toHaveBeenCalled());
    const next = onLinksChange.mock.calls[0][0] as SubmissionLink[];
    expect(next.filter((item) => item.is_default).map((item) => item.id)).toEqual(["link-2"]);
  });
});
