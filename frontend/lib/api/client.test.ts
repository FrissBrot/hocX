import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  backendFetch,
  browserApiFetch,
  browserApiUpload,
  DEFAULT_BROWSER_TIMEOUT_MS,
  LONG_RUNNING_TIMEOUT_MS,
  safeReturnPath,
  SERVER_FETCH_TIMEOUT_MS
} from "./client";

class FakeXhr {
  static last: FakeXhr;
  upload: { onprogress: ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
  status = 0;
  responseText = "";
  timeout = 0;
  withCredentials = false;
  method = "";
  url = "";
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  onabort: (() => void) | null = null;
  sent: unknown;
  constructor() {
    FakeXhr.last = this;
  }
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  send(body: unknown) {
    this.sent = body;
  }
  abort() {
    this.onabort?.();
  }
  respond(status: number, text: string) {
    this.status = status;
    this.responseText = text;
    this.onload?.();
  }
}

describe("browserApiUpload", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reports upload progress and resolves the JSON response", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    const onProgress = vi.fn();
    const body = new FormData();
    const promise = browserApiUpload<{ id: string }>("/api/upload", body, { timeoutMs: 1000, onProgress });

    const xhr = FakeXhr.last;
    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("/api/upload");
    expect(xhr.withCredentials).toBe(true);
    expect(xhr.timeout).toBe(1000);
    expect(xhr.sent).toBe(body);

    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 25, total: 100 });
    xhr.upload.onprogress?.({ lengthComputable: false, loaded: 50, total: 0 });
    expect(onProgress).toHaveBeenCalledTimes(1);
    expect(onProgress).toHaveBeenCalledWith(25, 100);

    xhr.respond(200, JSON.stringify({ id: "job-1" }));
    await expect(promise).resolves.toEqual({ id: "job-1" });
  });

  it("maps error responses like browserApiFetch", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    const promise = browserApiUpload("/api/upload", new FormData(), { timeoutMs: 1000 });
    FakeXhr.last.respond(413, JSON.stringify({ detail: "Datei zu gross" }));
    const error = await promise.catch((err: unknown) => err);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ message: "Datei zu gross", kind: "validation", status: 413 });
  });

  it("rejects with a timeout error", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    const promise = browserApiUpload("/api/upload", new FormData(), { timeoutMs: 1000 });
    FakeXhr.last.ontimeout?.();
    await expect(promise).rejects.toMatchObject({ kind: "timeout" });
  });
});

describe("Timeouts (Audit MAIN-FE-002/-004)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("browserApiFetch nutzt den Standard oder den uebergebenen laengeren Timeout", async () => {
    const timeoutSpy = vi.spyOn(AbortSignal, "timeout");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));

    await browserApiFetch("/api/a");
    expect(timeoutSpy).toHaveBeenLastCalledWith(DEFAULT_BROWSER_TIMEOUT_MS);

    await browserApiFetch("/api/b", { method: "POST", timeoutMs: LONG_RUNNING_TIMEOUT_MS });
    expect(timeoutSpy).toHaveBeenLastCalledWith(LONG_RUNNING_TIMEOUT_MS);
    // timeoutMs ist keine fetch-Option und darf nicht durchgereicht werden.
    const init = fetchSpy.mock.calls[1][1] as Record<string, unknown>;
    expect(init.timeoutMs).toBeUndefined();
    expect(init.method).toBe("POST");
  });

  it("backendFetch bricht ein haengendes Backend ab und wiederholt einen Timeout nicht", async () => {
    const timeoutSpy = vi.spyOn(AbortSignal, "timeout");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new DOMException("timed out", "TimeoutError"));
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    await expect(backendFetch("/api/auth/session")).resolves.toBeNull();
    expect(timeoutSpy).toHaveBeenCalledWith(SERVER_FETCH_TIMEOUT_MS);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("backendFetch wiederholt einen echten Verbindungsfehler einmal", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("socket hang up"))
      .mockResolvedValueOnce(new Response(JSON.stringify({ authenticated: true }), { status: 200 }));

    await expect(backendFetch("/api/auth/session")).resolves.toEqual({ authenticated: true });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });
});

describe("Überlast", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("schickt bei 503 overloaded auf die Überlast-Ansicht und merkt sich die Seite", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/protocols/1", search: "?x=1", assign });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "überlastet", code: "overloaded" }), { status: 503 }));

    await expect(browserApiFetch("/api/protocols")).rejects.toBeInstanceOf(ApiError);
    expect(assign).toHaveBeenCalledWith("/overload?from=%2Fprotocols%2F1%3Fx%3D1");
  });

  it("lässt db_busy und Admin-Aufrufe als normalen Fehler durch", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/", search: "", assign });
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValueOnce(new Response(JSON.stringify({ code: "db_busy" }), { status: 503 }));
    fetchSpy.mockResolvedValueOnce(new Response(JSON.stringify({ code: "overloaded" }), { status: 503 }));

    await expect(browserApiFetch("/api/protocols")).rejects.toBeInstanceOf(ApiError);
    await expect(browserApiFetch("/api/admin/system-status")).rejects.toBeInstanceOf(ApiError);
    expect(assign).not.toHaveBeenCalled();
  });

  it("springt nur auf eigene relative Pfade zurück", () => {
    expect(safeReturnPath("/protocols?tab=open")).toBe("/protocols?tab=open");
    expect(safeReturnPath(null)).toBe("/");
    expect(safeReturnPath("https://evil.example")).toBe("/");
    expect(safeReturnPath("//evil.example")).toBe("/");
    expect(safeReturnPath("/\\evil.example")).toBe("/");
    expect(safeReturnPath("/overload?from=%2F")).toBe("/");
    // URL-Parser entfernt Tab/Zeilenumbruch: "/\t/evil.example" würde sonst zu "//evil.example".
    expect(safeReturnPath("/\t/evil.example")).toBe("/");
    expect(safeReturnPath("/\n/evil.example")).toBe("/");
    expect(safeReturnPath("/%5cevil.example")).toBe("/%5cevil.example");
  });
});
