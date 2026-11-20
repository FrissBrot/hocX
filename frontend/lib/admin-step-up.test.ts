import { beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => vi.fn());
const assertion = vi.hoisted(() => vi.fn(async () => ({ id: "cred" })));
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (path: string, init?: RequestInit) => api(path, init) }));
vi.mock("@/lib/webauthn", () => ({ getPasskeyAssertion: assertion }));

import { stepUpFetch } from "./admin-step-up";

beforeEach(() => vi.clearAllMocks());

it("bindet die Passkey-Bestätigung an Methode, Pfad und Body-Hash und sendet sie im Header", async () => {
  api.mockImplementation(async (path: string) =>
    path === "/api/admin/mfa/step-up/start" ? { flow_token: "flow-1", public_key: { challenge: "c" } } : { ok: true }
  );
  const body = JSON.stringify({ email: "a@b.example" });

  await stepUpFetch("admin-manage", "/api/admin/admins", { method: "post", body });

  const start = JSON.parse(api.mock.calls[0][1].body);
  const expectedHash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body))), (b) =>
    b.toString(16).padStart(2, "0")
  ).join("");
  expect(start).toEqual({ purpose: "admin-manage", method: "POST", path: "/api/admin/admins", body_sha256: expectedHash });
  expect(assertion).toHaveBeenCalledWith({ challenge: "c" });
  const [path, init] = api.mock.calls[1];
  expect(path).toBe("/api/admin/admins");
  expect(init.body).toBe(body);
  const header = init.headers["X-Hocx-Step-Up"] as string;
  const decoded = JSON.parse(atob(header.replace(/-/g, "+").replace(/_/g, "/")));
  expect(decoded).toEqual({ flow_token: "flow-1", credential: { id: "cred" } });
});
