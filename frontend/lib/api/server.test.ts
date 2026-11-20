import { headers } from "next/headers";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({ getAll: () => [{ name: "hocx_admin_session", value: "s" }] })),
  headers: vi.fn()
}));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));

import type { SessionInfo } from "@/types/api";

import { backendFetchWithSession, withoutBridgeRedirect } from "./server";

describe("backendFetchWithSession (SEC-AUTH-001)", () => {
  afterEach(() => vi.restoreAllMocks());

  function mockIncoming(values: Record<string, string>) {
    vi.mocked(headers).mockResolvedValue(new Headers(values) as Awaited<ReturnType<typeof headers>>);
    return vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
  }

  it("reicht für die Admin-API Gate-Header und Host vom Admin-Entrypoint weiter", async () => {
    const fetchSpy = mockIncoming({ host: "admin.example.ch", "x-hocx-admin-gate": "gate" });

    await backendFetchWithSession("/api/admin/tenants");

    expect(fetchSpy.mock.calls[0][1]?.headers).toEqual({
      "x-hocx-admin-gate": "gate",
      "x-forwarded-host": "admin.example.ch",
      Cookie: "hocx_admin_session=s"
    });
  });

  it("schickt den Gate-Header nie an andere Endpunkte", async () => {
    const fetchSpy = mockIncoming({ host: "admin.example.ch", "x-hocx-admin-gate": "gate" });

    await backendFetchWithSession("/api/auth/session");

    expect(fetchSpy.mock.calls[0][1]?.headers).toEqual({ Cookie: "hocx_admin_session=s" });
  });
});

describe("withoutBridgeRedirect", () => {
  it("verwirft den Bridge-Link einer serverseitig geladenen Sitzung", () => {
    // Serverseitig sieht das Backend den Host "backend" und liefert immer einen Bridge-Link,
    // auch auf der richtigen Domain (Bestätigungsfenster nach jedem Seitenaufruf).
    const session = { authenticated: true, bridge_redirect_url: "https://app.example/auth/bridge#token=x" } as SessionInfo;
    const result = withoutBridgeRedirect(session);
    expect(result.bridge_redirect_url).toBeNull();
    expect(result.authenticated).toBe(true);
    expect(session.bridge_redirect_url).not.toBeNull();
  });

  it("lässt eine Sitzung ohne Bridge-Link unverändert", () => {
    const session = { authenticated: true, bridge_redirect_url: null } as SessionInfo;
    expect(withoutBridgeRedirect(session)).toBe(session);
  });
});
