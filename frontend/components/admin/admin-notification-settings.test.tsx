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

import { AdminNotificationSettings } from "./admin-notification-settings";
import { NotificationSettings } from "@/types/api";

function makeSettings(overrides: Partial<NotificationSettings> = {}): NotificationSettings {
  return {
    ntfy_enabled: true,
    ntfy_server_url: "https://ntfy.example",
    ntfy_topic: "hocx-alerts",
    ntfy_token_set: true,
    admin_url: null,
    reminder_hours: 6,
    status_token: null,
    status_url: null,
    last_sent_at: null,
    last_send_error: null,
    last_send_error_at: null,
    ...overrides,
  };
}

describe("AdminNotificationSettings", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    confirmMock.mockReset();
  });

  it("speichert ohne Token, solange keins eingegeben wurde (gespeichertes bleibt)", async () => {
    browserApiFetchMock.mockResolvedValue(makeSettings({ ntfy_topic: "neu" }));
    render(<AdminNotificationSettings initialSettings={makeSettings()} />);

    fireEvent.change(screen.getByDisplayValue("hocx-alerts"), { target: { value: "neu" } });
    fireEvent.click(screen.getByRole("button", { name: "Speichern" }));

    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalled());
    const [path, init] = browserApiFetchMock.mock.calls[0];
    expect(path).toBe("/api/admin/notifications");
    expect(JSON.parse(init.body)).toMatchObject({ ntfy_topic: "neu", ntfy_token: null, ntfy_enabled: true });
    expect(showToastMock).toHaveBeenCalledWith("Einstellungen gespeichert.", "success");
  });

  it("Testnachricht erst nach dem Speichern und mit Fehlermeldung vom Server", async () => {
    browserApiFetchMock
      .mockResolvedValueOnce({ ok: false, error: "ntfy antwortete mit HTTP 403" })
      .mockResolvedValueOnce(makeSettings());
    render(<AdminNotificationSettings initialSettings={makeSettings()} />);

    const testButton = screen.getByRole("button", { name: "Testnachricht senden" });
    fireEvent.change(screen.getByDisplayValue("hocx-alerts"), { target: { value: "x" } });
    expect(testButton).toBeDisabled();
    fireEvent.change(screen.getByDisplayValue("x"), { target: { value: "hocx-alerts" } });
    fireEvent.click(testButton);

    await waitFor(() => expect(showToastMock).toHaveBeenCalledWith("Testnachricht fehlgeschlagen: ntfy antwortete mit HTTP 403", "error"));
  });

  it("zeigt die Status-URL und fragt vor dem Erneuern des Tokens nach", async () => {
    confirmMock.mockResolvedValue(false);
    render(
      <AdminNotificationSettings
        initialSettings={makeSettings({ status_token: "tok", status_url: "https://hocx.example/api/system-status/summary?token=tok" })}
      />,
    );

    expect(screen.getByText("https://hocx.example/api/system-status/summary?token=tok")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Neues Token erzeugen" }));

    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    expect(browserApiFetchMock).not.toHaveBeenCalled();
  });
});
