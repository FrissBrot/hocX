import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => vi.fn());
const replace = vi.hoisted(() => vi.fn());
const webauthn = vi.hoisted(() => ({
  browserSupportsPasskeys: vi.fn(() => true),
  createPasskeyCredential: vi.fn(async () => ({ id: "neu" })),
  getPasskeyAssertion: vi.fn(async () => ({ id: "vorhanden" })),
}));
vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, browserApiFetch: (url: string, init?: { method?: string; body?: string }) => api(url, init) };
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/webauthn", () => webauthn);

import { ApiError } from "@/lib/api/client";
import AdminLoginPage from "./page";

function pending(status: "setup_required" | "verification_required") {
  return {
    status,
    ticket: "ticket-1",
    required: true,
    user_display_name: "Ops",
    user_email: "ops@example.com",
    tenant_name: null,
    available_methods: status === "verification_required" ? [{ factor_type: "webauthn", label: "Passkey" }] : [],
    default_factor_type: status === "verification_required" ? "webauthn" : null,
    default_factor_label: null,
    can_add_totp: false,
    can_add_passkey: status === "setup_required",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  webauthn.browserSupportsPasskeys.mockReturnValue(true);
});

async function loginWith(mfa: ReturnType<typeof pending>, extra: (url: string, init?: { body?: string }) => unknown) {
  api.mockImplementation((url: string, init?: { body?: string }) => {
    if (url === "/api/admin/auth/session") return Promise.resolve({ authenticated: false });
    if (url === "/api/admin/auth/login") return Promise.resolve({ authenticated: false, mfa });
    return Promise.resolve(extra(url, init));
  });
  render(<AdminLoginPage />);
  fireEvent.change(screen.getByLabelText("E-Mail"), { target: { value: "ops@example.com" } });
  fireEvent.change(screen.getByLabelText("Passwort"), { target: { value: "ein-langes-passwort" } });
  fireEvent.click(screen.getByRole("button", { name: "Einloggen" }));
}

it("bietet weder SSO noch TOTP an", async () => {
  await loginWith(pending("verification_required"), () => null);
  await screen.findByRole("button", { name: "Mit Passkey bestätigen" });
  expect(screen.queryByText(/TOTP|Authenticator|SSO/)).not.toBeInTheDocument();
  expect(api).not.toHaveBeenCalledWith(expect.stringContaining("oidc"), expect.anything());
});

it("bestätigt die Anmeldung mit dem vorhandenen Passkey", async () => {
  await loginWith(pending("verification_required"), (url) => {
    if (url === "/api/admin/auth/mfa/passkey/start") return { flow_token: "flow-1", public_key: { challenge: "c", rpId: "admin.example" } };
    if (url === "/api/admin/auth/mfa/passkey/verify") return { authenticated: true };
    return null;
  });
  fireEvent.click(await screen.findByRole("button", { name: "Mit Passkey bestätigen" }));

  await waitFor(() => expect(replace).toHaveBeenCalledWith("/admin"));
  expect(webauthn.getPasskeyAssertion).toHaveBeenCalledWith({ challenge: "c", rpId: "admin.example" });
  const verify = api.mock.calls.find(([url]) => url === "/api/admin/auth/mfa/passkey/verify");
  expect(JSON.parse(verify?.[1]?.body ?? "{}")).toEqual({ flow_token: "flow-1", credential: { id: "vorhanden" } });
});

it("verlangt ohne Passkey die Einrichtung, bevor es eine Sitzung gibt", async () => {
  await loginWith(pending("setup_required"), (url) => {
    if (url === "/api/admin/auth/mfa/passkey/setup/start") return { flow_token: "flow-2", public_key: { challenge: "c", rp: { id: "admin.example" } } };
    if (url === "/api/admin/auth/mfa/passkey/setup/complete") return { authenticated: true };
    return null;
  });
  expect(await screen.findByText("Für Platform-Admin-Konten ist ein Passkey Pflicht")).toBeInTheDocument();
  expect(replace).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Bezeichnung"), { target: { value: "YubiKey" } });
  fireEvent.click(screen.getByRole("button", { name: "Passkey einrichten und anmelden" }));

  await waitFor(() => expect(replace).toHaveBeenCalledWith("/admin"));
  const complete = api.mock.calls.find(([url]) => url === "/api/admin/auth/mfa/passkey/setup/complete");
  expect(JSON.parse(complete?.[1]?.body ?? "{}")).toEqual({ flow_token: "flow-2", label: "YubiKey", credential: { id: "neu" } });
});

it("zeigt einen abgelehnten Passkey in der UI-Sprache", async () => {
  await loginWith(pending("verification_required"), (url) => {
    if (url === "/api/admin/auth/mfa/passkey/start") return { flow_token: "flow-1", public_key: {} };
    if (url === "/api/admin/auth/mfa/passkey/verify") {
      return Promise.reject(new ApiError("ROH", "auth", 401, { code: "passkey_unknown", message: "ROH" }));
    }
    return null;
  });
  fireEvent.click(await screen.findByRole("button", { name: "Mit Passkey bestätigen" }));

  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Dieser Passkey gehört nicht zu diesem Konto."));
  expect(replace).not.toHaveBeenCalled();
});

it("erklärt, dass ohne Passkey-Unterstützung keine Admin-Anmeldung möglich ist", async () => {
  webauthn.browserSupportsPasskeys.mockReturnValue(false);
  await loginWith(pending("setup_required"), () => null);
  expect(await screen.findByText(/Die Admin-Anmeldung ist nur mit Passkey möglich/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Passkey einrichten und anmelden" })).not.toBeInTheDocument();
});
