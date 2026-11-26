import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

import { webdavConnectBody } from "@/lib/files/file-import";

import { ImportWebdavForm } from "./import-webdav-form";

describe("webdavConnectBody", () => {
  it("schickt nur die Felder der gewählten Vorlage", () => {
    const base = { server: " cloud.verein.example ", kdriveId: " 42 ", url: " https://dav.example/x/ ", username: " anna ", password: " pw " };
    expect(webdavConnectBody({ ...base, preset: "kdrive" })).toEqual({ preset: "kdrive", username: "anna", password: " pw ", kdrive_id: "42" });
    expect(webdavConnectBody({ ...base, preset: "nextcloud" })).toEqual({ preset: "nextcloud", username: "anna", password: " pw ", server: "cloud.verein.example" });
    expect(webdavConnectBody({ ...base, preset: "generic" })).toEqual({ preset: "generic", username: "anna", password: " pw ", url: "https://dav.example/x/" });
  });
});

describe("ImportWebdavForm", () => {
  beforeEach(() => browserApiFetchMock.mockReset());

  it("sendet erst vollständig, per Enter, und zeigt Fehlercodes übersetzt", async () => {
    browserApiFetchMock.mockRejectedValueOnce({ detail: { code: "webdav_auth_failed" } });
    browserApiFetchMock.mockResolvedValueOnce({ id: "j1", status: "draft" });
    const onJob = vi.fn();
    render(<ImportWebdavForm jobId="j1" onJob={onJob} />);
    const submit = screen.getByRole("button", { name: "Verbinden" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/^Benutzername/), { target: { value: "anna@verein.test" } });
    const password = screen.getByLabelText(/^App-Passwort/);
    fireEvent.change(password, { target: { value: "geheim-1" } });
    expect(password).toHaveAttribute("type", "password");
    expect(submit).toBeEnabled();
    fireEvent.submit(password.closest("form")!);
    await screen.findByText("Benutzername oder App-Passwort stimmen nicht.");
    expect(browserApiFetchMock).toHaveBeenCalledWith("/api/cloud-import/jobs/j1/webdav/connect", expect.objectContaining({ method: "POST" }));
    const body = JSON.parse(browserApiFetchMock.mock.calls[0][1].body as string);
    expect(body).toEqual({ preset: "kdrive", username: "anna@verein.test", password: "geheim-1" });
    fireEvent.submit(password.closest("form")!);
    await waitFor(() => expect(onJob).toHaveBeenCalledWith({ id: "j1", status: "draft" }));
    // Passwort nach Erfolg aus dem Formular entfernt
    expect(password).toHaveValue("");
  });

  it("verlangt bei Nextcloud die Serveradresse", () => {
    render(<ImportWebdavForm jobId="j1" onJob={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Anbieter"), { target: { value: "nextcloud" } });
    fireEvent.change(screen.getByLabelText(/^Benutzername/), { target: { value: "anna" } });
    fireEvent.change(screen.getByLabelText(/^App-Passwort/), { target: { value: "x" } });
    expect(screen.getByRole("button", { name: "Verbinden" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/^Serveradresse/), { target: { value: "cloud.verein.example" } });
    expect(screen.getByRole("button", { name: "Verbinden" })).toBeEnabled();
  });
});
