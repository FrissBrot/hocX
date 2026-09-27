import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, browserApiUpload } from "./client";

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
