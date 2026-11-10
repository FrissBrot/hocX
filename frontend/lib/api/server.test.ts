import { describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({ cookies: vi.fn(), headers: vi.fn() }));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));

import type { SessionInfo } from "@/types/api";

import { withoutBridgeRedirect } from "./server";

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
