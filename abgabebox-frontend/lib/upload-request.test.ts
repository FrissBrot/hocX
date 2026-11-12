import { describe, expect, it } from "vitest";

import { parseResponseHeaders, sendUpload, uploadPercent, type UploadPhase } from "./upload-request";

// Minimaler XHR-Ersatz: der Test steuert Fortschritt und Antwort selbst.
class FakeXhr {
  status = 0;
  responseText = "";
  timeout = 0;
  rawHeaders = "";
  method = "";
  url = "";
  sentBody: unknown = null;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  onabort: (() => void) | null = null;
  upload: { onprogress: ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null; onload: (() => void) | null } = {
    onprogress: null,
    onload: null,
  };
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  send(body: unknown) {
    this.sentBody = body;
  }
  abort() {
    this.onabort?.();
  }
  getAllResponseHeaders() {
    return this.rawHeaders;
  }
  respond(status: number, body: string, headers = "") {
    this.status = status;
    this.responseText = body;
    this.rawHeaders = headers;
    this.onload?.();
  }
}

function start(onPhase?: (phase: UploadPhase) => void) {
  const xhr = new FakeXhr();
  const body = new FormData();
  const promise = sendUpload("/api/upload", body, {
    timeoutMs: 1234,
    onPhase,
    createXhr: () => xhr as unknown as XMLHttpRequest,
  });
  return { xhr, body, promise };
}

describe("uploadPercent", () => {
  it("rounds and clamps to 0..100", () => {
    expect(uploadPercent(0, 100)).toBe(0);
    expect(uploadPercent(421, 1000)).toBe(42);
    expect(uploadPercent(2000, 1000)).toBe(100);
  });

  it("returns 0 without a known total", () => {
    expect(uploadPercent(10, 0)).toBe(0);
  });
});

describe("parseResponseHeaders", () => {
  it("parses CRLF separated headers case-insensitively", () => {
    const headers = parseResponseHeaders("content-type: application/json\r\nretry-after: 12\r\n");
    expect(headers.get("Retry-After")).toBe("12");
    expect(headers.get("Content-Type")).toBe("application/json");
  });
});

describe("sendUpload", () => {
  it("posts the form data with the given timeout", () => {
    const { xhr, body } = start();
    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("/api/upload");
    expect(xhr.timeout).toBe(1234);
    expect(xhr.sentBody).toBe(body);
  });

  it("reports progress in percent and then the processing phase", async () => {
    const phases: UploadPhase[] = [];
    const { xhr, promise } = start((phase) => phases.push(phase));
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 25, total: 100 });
    xhr.upload.onprogress?.({ lengthComputable: false, loaded: 50, total: 0 });
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 100, total: 100 });
    xhr.upload.onload?.();
    xhr.respond(200, JSON.stringify({ image_duplicate_warnings: [] }), "content-type: application/json");
    const response = await promise;
    expect(phases).toEqual([
      { phase: "uploading", percent: 0 },
      { phase: "uploading", percent: 25 },
      { phase: "uploading", percent: 100 },
      { phase: "processing" },
    ]);
    expect(response.ok).toBe(true);
    expect(await response.json()).toEqual({ image_duplicate_warnings: [] });
  });

  it("resolves error statuses like fetch, including Retry-After and a cloneable body", async () => {
    const { xhr, promise } = start();
    xhr.respond(503, JSON.stringify({ code: "busy" }), "Retry-After: 7");
    const response = await promise;
    expect(response.ok).toBe(false);
    expect(response.status).toBe(503);
    expect(response.headers.get("Retry-After")).toBe("7");
    expect(await response.clone().json()).toEqual({ code: "busy" });
    expect(await response.json()).toEqual({ code: "busy" });
  });

  it("rejects with TypeError on network errors", async () => {
    const { xhr, promise } = start();
    xhr.onerror?.();
    await expect(promise).rejects.toBeInstanceOf(TypeError);
  });

  it("rejects with a TimeoutError on timeout", async () => {
    const { xhr, promise } = start();
    xhr.ontimeout?.();
    await expect(promise).rejects.toMatchObject({ name: "TimeoutError" });
  });
});
