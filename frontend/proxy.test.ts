import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { proxy } from "./proxy";

function unauthenticatedBackend() {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ authenticated: false }), { status: 200 }));
}

describe("proxy", () => {
  afterEach(() => vi.restoreAllMocks());

  it("leitet nicht eingeloggte Besucher der App auf /login um", async () => {
    unauthenticatedBackend();

    const response = await proxy(new NextRequest("https://app.example.ch/photos"));

    expect(response.headers.get("location")).toBe("https://app.example.ch/login");
  });

  it("lässt öffentliche Freigabe-Links ohne Login durch", async () => {
    const fetchSpy = unauthenticatedBackend();

    const response = await proxy(new NextRequest("https://app.example.ch/share/abc123"));

    expect(response.headers.get("location")).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("lässt die Bestätigung des Domain-Wechsels ohne Login durch", async () => {
    const fetchSpy = unauthenticatedBackend();

    const response = await proxy(new NextRequest("https://kunde.example.org/auth/bridge?token=abc"));

    expect(response.headers.get("location")).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("schreibt die Website-Domain ohne Login auf /website um", async () => {
    vi.stubEnv("TRAEFIK_WEBSITE_DOMAIN", "www.example.ch");
    vi.resetModules();
    const { proxy: websiteProxy } = await import("./proxy");
    const fetchSpy = unauthenticatedBackend();

    const response = await websiteProxy(new NextRequest("http://0.0.0.0:3000/", { headers: { host: "www.example.ch" } }));

    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("x-middleware-rewrite")).toBe("http://0.0.0.0:3000/website");
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllEnvs();
  });

  it("schreibt die Admin-Domain auch hinter der Bind-Adresse 0.0.0.0 auf /admin um", async () => {
    // Audit MAIN-FE-003: nextUrl.hostname ist hinter HOSTNAME=0.0.0.0 die Bind-Adresse.
    vi.stubEnv("TRAEFIK_ADMIN_DOMAIN", "admin.example.ch");
    vi.resetModules();
    const { proxy: adminProxy } = await import("./proxy");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ authenticated: true }), { status: 200 }));

    const response = await adminProxy(new NextRequest("http://0.0.0.0:3000/", { headers: { host: "admin.example.ch" } }));

    expect(response.headers.get("x-middleware-rewrite")).toBe("http://0.0.0.0:3000/admin");
    vi.unstubAllEnvs();
  });

  it("rendert bei haengendem Backend nach dem Timeout normal statt zu blockieren", async () => {
    // Audit MAIN-FE-002: der Session-Check traegt ein Timeout-Signal; laeuft es ab, gilt der
    // Status als unbekannt (null) und die Seite rendert ohne Umleitung.
    const timeoutSpy = vi.spyOn(AbortSignal, "timeout");
    vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("timed out", "TimeoutError")));
    }));
    const controller = new AbortController();
    timeoutSpy.mockReturnValue(controller.signal);

    const pending = proxy(new NextRequest("https://app.example.ch/photos"));
    expect(timeoutSpy).toHaveBeenCalledWith(5_000);
    controller.abort();
    const response = await pending;

    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });
});
