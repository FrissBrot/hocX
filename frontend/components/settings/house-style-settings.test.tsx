import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HouseStyleSettings } from "./house-style-settings";

const { apiFetch, preview, toast, confirm } = vi.hoisted(() => ({ apiFetch: vi.fn(), preview: vi.fn(), toast: vi.fn(), confirm: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApiFetch: apiFetch }));
vi.mock("@/lib/documents/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/documents/api")>()), previewDocument: preview }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirm }));

const tokens = {
  primary_color: "#174b7a", secondary_color: "#4f6d7a", font: "style", custom_fonts: { regular: null, bold: null, italic: null, bold_italic: null },
  base_size: 11 as const, line_spacing: "normal", margins: "normal", orientation: "portrait", logo_asset_id: null, footer_image_asset_id: null,
  sender: "", sender_color: null, place: "", header: "standard", footer: "standard", title_page: "none", toc: "off", numbering: false, toc_block_titles: true, show_metadata: false, watermark_draft: true,
  verify_show_url: true, verify_show_id: true, verify_show_qr: true,
};
const style = { id: "s1", name: "Standard", style_key: "modern", tokens, is_default: true, version: 1, updated_at: "" };

describe("HouseStyleSettings", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    apiFetch.mockReset();
    preview.mockReset().mockResolvedValue({ pages: ["data:image/png;base64,AAA"] });
  });

  it("previews unsaved tokens live and saves them", async () => {
    render(<HouseStyleSettings initialStyles={[style]} initialAssets={[]} initialLanguage="de" languages={["de", "en"]} canEdit />);
    fireEvent.change(screen.getByLabelText("Kopfzeile"), { target: { value: "bar" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    await waitFor(() => expect(preview).toHaveBeenCalled());
    const request = preview.mock.calls.at(-1)[0];
    expect(request.style_override).toMatchObject({ style_key: "modern", tokens: { header: "bar" } });

    apiFetch.mockResolvedValue({ ...style, tokens: { ...tokens, header: "bar" }, version: 2 });
    fireEvent.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith("/api/document-styles/s1", expect.objectContaining({ method: "PATCH" })));
    expect(JSON.parse(apiFetch.mock.calls[0][1].body).tokens.header).toBe("bar");
  });

  it("previews every change of the authenticity options", async () => {
    render(<HouseStyleSettings initialStyles={[style]} initialAssets={[]} initialLanguage="de" languages={["de"]} canEdit />);
    expect(screen.getByRole("group", { name: "Echtheitsprüfung im Dokument" })).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("QR-Code auf der letzten Seite"));
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    await waitFor(() => expect(preview.mock.calls.at(-1)?.[0].style_override.tokens).toMatchObject({ verify_show_qr: false, verify_show_url: true, verify_show_id: true }));
  });

  it("is read-only without edit rights", () => {
    render(<HouseStyleSettings initialStyles={[style]} initialAssets={[]} initialLanguage="de" languages={["de"]} canEdit={false} />);
    expect(screen.getByLabelText("Kopfzeile")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Neuer Hausstil" })).not.toBeInTheDocument();
  });
});
