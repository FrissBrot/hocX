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
});
