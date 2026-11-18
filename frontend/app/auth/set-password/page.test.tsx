import { StrictMode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => vi.fn());
const replace = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, browserApiFetch: (url: string, init?: { method?: string; body?: string }) => api(url, init) };
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));

import { ConfirmProvider } from "@/contexts/confirm-context";
import { ApiError } from "@/lib/api/client";
import SetPasswordPage from "./page";

// Stark nach lib/password-strength.ts: vier Zeichenarten, kein Name/Wort
const PASSWORD = "Tanne-Kiesel-Wolke-7";

function pending(required: boolean) {
  return {
    status: "setup_required",
    ticket: "ticket-1",
    required,
    user_display_name: "Neu Person",
    user_email: "neu@example.com",
    tenant_name: "Pfadi Test",
    available_methods: [],
    default_factor_type: null,
    default_factor_label: null,
    can_add_totp: true,
    can_add_passkey: true,
    can_skip: !required,
  };
}

let mfaRequired = false;

beforeEach(() => {
  vi.clearAllMocks();
  mfaRequired = false;
  window.history.replaceState(null, "", "/auth/set-password#token=abc123&kind=invite");
  api.mockImplementation((url: string) => {
    if (url.endsWith("/preview")) return Promise.resolve({ purpose: "invite", display_name: "Neu Person", email: "neu@example.com", tenant_name: "Pfadi Test" });
    if (url.endsWith("/account-link/complete")) return Promise.resolve({ purpose: "invite", mfa: pending(mfaRequired), mfa_required: mfaRequired });
    if (url.endsWith("/mfa/setup/skip")) return Promise.resolve({ authenticated: true, bridge_redirect_url: null, mfa: null });
    if (url.endsWith("/mfa/totp/setup/start")) {
      return Promise.resolve({ flow_token: "flow-1", secret: "JBSWY3DPEHPK3PXP", manual_entry_key: "JBSWY3DPEHPK3PXP", provisioning_uri: "otpauth://totp/hocX:neu@example.com?secret=JBSWY3DPEHPK3PXP&issuer=hocX", issuer: "hocX", account_name: "neu@example.com" });
    }
    if (url.endsWith("/mfa/totp/setup/complete")) return Promise.resolve({ authenticated: true, bridge_redirect_url: null, mfa: null });
    return Promise.reject(new Error(`unerwartet: ${url}`));
  });
});

function renderPage() {
  return render(<ConfirmProvider><SetPasswordPage /></ConfirmProvider>);
}

async function setPassword(value = PASSWORD) {
  const [password, repeat] = await screen.findAllByLabelText(/^(Neues Passwort|Passwort wiederholen)$/);
  fireEvent.change(password, { target: { value } });
  fireEvent.change(repeat, { target: { value } });
}

it("reads the token from the fragment, removes it from the address bar and sends it only in the body", async () => {
  renderPage();
  expect(await screen.findByRole("heading", { name: "Konto einrichten" })).toBeInTheDocument();
  expect(window.location.hash).toBe("");
  expect(api).toHaveBeenCalledWith("/api/auth/account-link/preview", { method: "POST", body: JSON.stringify({ token: "abc123" }) });
  expect(screen.getByText("Passwort")).toBeInTheDocument();
  expect(screen.getByText("Zweiter Faktor")).toBeInTheDocument();
});

it("shows the live strength and enables saving only for a strong, repeated password", async () => {
  renderPage();
  const [password, repeat] = await screen.findAllByLabelText(/^(Neues Passwort|Passwort wiederholen)$/);
  const submit = screen.getByRole("button", { name: "Passwort festlegen" });
  fireEvent.change(password, { target: { value: "kurz" } });
  expect(screen.getByText("Zu kurz")).toBeInTheDocument();
  // Name der Person drückt die Bewertung auf «Schwach»
  fireEvent.change(password, { target: { value: "NeuPerson-2026!" } });
  fireEvent.change(repeat, { target: { value: "NeuPerson-2026!" } });
  expect(screen.getByText("Schwach")).toBeInTheDocument();
  expect(screen.getByText(/leicht zu erraten/)).toBeInTheDocument();
  expect(submit).toBeDisabled();
  fireEvent.change(password, { target: { value: PASSWORD } });
  fireEvent.change(repeat, { target: { value: `${PASSWORD}x` } });
  expect(screen.getByText("Die Passwörter stimmen nicht überein.")).toBeInTheDocument();
  expect(submit).toBeDisabled();
  fireEvent.change(repeat, { target: { value: PASSWORD } });
  expect(screen.getByText("Sehr stark")).toBeInTheDocument();
  expect(submit).toBeEnabled();
  fireEvent.click(submit);
  expect(await screen.findByRole("heading", { name: "Zweiten Faktor einrichten" })).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/api/auth/account-link/complete", { method: "POST", body: JSON.stringify({ token: "abc123", password: PASSWORD }) });
});

it("offers «Später einrichten» without obligation and logs in after confirming", async () => {
  renderPage();
  await setPassword();
  fireEvent.click(screen.getByRole("button", { name: "Passwort festlegen" }));
  fireEvent.click(await screen.findByRole("button", { name: "Später einrichten" }));
  fireEvent.click(await screen.findByRole("button", { name: "Überspringen" }));
  expect(await screen.findByRole("heading", { name: "Alles bereit" })).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/api/auth/mfa/setup/skip", { method: "POST", body: JSON.stringify({ ticket: "ticket-1" }) });
  expect(screen.getByText("Nicht eingerichtet")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Zu hocX" }));
  expect(replace).toHaveBeenCalledWith("/");
});

it("hides «Später einrichten» when MFA is mandatory and sets up the authenticator app", async () => {
  mfaRequired = true;
  renderPage();
  await setPassword();
  fireEvent.click(screen.getByRole("button", { name: "Passwort festlegen" }));
  expect(await screen.findByText("Pflicht in Pfadi Test.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Später einrichten" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("radio", { name: /Authenticator-App/ }));
  fireEvent.click(screen.getByRole("button", { name: "Weiter" }));
  expect(await screen.findByRole("heading", { name: "Authenticator-App einrichten" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "In Authenticator-App öffnen" })).toHaveAttribute("href", expect.stringMatching(/^otpauth:\/\/totp\//));
  const submit = screen.getByRole("button", { name: "Aktivieren und anmelden" });
  expect(submit).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Code-Ziffer 1"), { target: { value: "123456" } });
  await waitFor(() => expect(submit).toBeEnabled());
  fireEvent.click(submit);
  expect(await screen.findByRole("heading", { name: "Alles bereit" })).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/api/auth/mfa/totp/setup/complete", { method: "POST", body: JSON.stringify({ flow_token: "flow-1", code: "123456", label: null }) });
  expect(screen.getByText("Authenticator-App")).toBeInTheDocument();
});

it("shows an invalid invitation without a token", async () => {
  window.history.replaceState(null, "", "/auth/set-password#kind=invite");
  renderPage();
  expect(await screen.findByRole("heading", { name: "Einladung ungültig" })).toBeInTheDocument();
  expect(api).not.toHaveBeenCalled();
});

it("keeps the token under React StrictMode (effects run twice in development)", async () => {
  render(<StrictMode><ConfirmProvider><SetPasswordPage /></ConfirmProvider></StrictMode>);
  expect(await screen.findByRole("heading", { name: "Konto einrichten" })).toBeInTheDocument();
  expect(await screen.findAllByLabelText(/^(Neues Passwort|Passwort wiederholen)$/)).toHaveLength(2);
  expect(screen.queryByRole("heading", { name: "Einladung ungültig" })).not.toBeInTheDocument();
  expect(window.location.hash).toBe("");
});

it("shows «Kurz gesperrt» instead of «link invalid» when the preview answers 429", async () => {
  api.mockRejectedValue(new ApiError("Too many requests", "backend", 429, { code: "rate_limited", message: "Too many requests" }));
  renderPage();
  expect(await screen.findByRole("heading", { name: "Kurz gesperrt" })).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Zu viele Versuche.");
});

it("ends a password reset at the login without a second step", async () => {
  window.history.replaceState(null, "", "/auth/set-password#token=abc123");
  api.mockImplementation((url: string) =>
    Promise.resolve(url.endsWith("/preview")
      ? { purpose: "password_reset", display_name: "Neu Person", email: "neu@example.com", tenant_name: "Pfadi Test" }
      : { purpose: "password_reset", mfa: null, mfa_required: null }));
  renderPage();
  await setPassword();
  fireEvent.click(screen.getByRole("button", { name: "Passwort speichern" }));
  expect(await screen.findByText(/Dein Passwort ist geändert/)).toBeInTheDocument();
  expect(screen.queryByText("Zweiter Faktor")).not.toBeInTheDocument();
});
