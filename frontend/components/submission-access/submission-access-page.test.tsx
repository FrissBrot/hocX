import { render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import messages from "@/messages/de/submissionAccess.json";
import { ConfirmProvider } from "@/contexts/confirm-context";
import { ToastProvider } from "@/contexts/toast-context";

const fetchMock = vi.fn();
vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, browserApiFetch: (...args: unknown[]) => fetchMock(...args) };
});

import { SubmissionAccessPage } from "./submission-access-page";

function renderPage() {
  return render(
    <NextIntlClientProvider locale="de" messages={{ submissionAccess: messages }}>
      <ToastProvider><ConfirmProvider><SubmissionAccessPage /></ConfirmProvider></ToastProvider>
    </NextIntlClientProvider>,
  );
}

const VIEW = {
  tenant_name: "Pfadi", person_name: "Anna", title: "Berichte", description: null, element_label: "Badetag",
  window_start: null, window_end: "2026-11-20", status: "submitted", submitted_at: "2026-11-14T10:00:00Z",
  files: [{ id: "f1", name: "bericht.pdf", size: 1200, scan_status: "clean" }],
  can_withdraw: true, can_upload: true, allowed_file_types: ["pdf"], max_file_size_mb: 20, remaining_files: 4,
};

describe("SubmissionAccessPage", () => {
  afterEach(() => {
    fetchMock.mockReset();
    window.sessionStorage.clear();
  });

  it("liest das Token aus dem Fragment, entfernt es aus der Adresse und schickt es nur im Body", async () => {
    window.history.replaceState(null, "", "/abgabe/verwalten#abcdefghijklmnop");
    fetchMock.mockResolvedValue(VIEW);
    renderPage();
    expect(await screen.findByText("Berichte")).toBeInTheDocument();
    expect(window.location.hash).toBe("");
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/public/submission-access/view");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ token: "abcdefghijklmnop" });
    expect(screen.getByRole("button", { name: "Abgabe zurückziehen" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Weitere Dateien abgeben" })).toBeInTheDocument();
  });

  it("zeigt ohne Token sofort «ungültig»", async () => {
    window.history.replaceState(null, "", "/abgabe/verwalten");
    renderPage();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("ungültig"));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
