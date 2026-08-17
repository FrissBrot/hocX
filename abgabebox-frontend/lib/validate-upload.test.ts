import { describe, expect, it } from "vitest";

import { getExtension, validateUploadFiles } from "./validate-upload";

function fakeFile(name: string, sizeBytes: number): File {
  return new File([new Uint8Array(sizeBytes)], name);
}

describe("getExtension", () => {
  it("lowercases the extension", () => {
    expect(getExtension("Foto.JPG")).toBe("jpg");
  });

  it("returns empty string for a filename without an extension", () => {
    expect(getExtension("readme")).toBe("");
  });

  it("uses the last segment for filenames with multiple dots", () => {
    expect(getExtension("archiv.tar.gz")).toBe("gz");
  });
});

describe("validateUploadFiles", () => {
  const opts = { maxFiles: 2, allowedFileTypes: ["pdf", "jpg"], maxFileSizeMb: 5 };

  it("accepts a valid single file", () => {
    const result = validateUploadFiles([fakeFile("beleg.pdf", 1024)], opts);
    expect(result).toEqual({ ok: true });
  });

  it("rejects more files than maxFiles", () => {
    const files = [fakeFile("a.pdf", 100), fakeFile("b.pdf", 100), fakeFile("c.pdf", 100)];
    const result = validateUploadFiles(files, opts);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toContain("Maximal 2");
  });

  it("rejects a disallowed file extension", () => {
    const result = validateUploadFiles([fakeFile("script.exe", 100)], opts);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toContain("script.exe");
  });

  it("rejects a file over the size limit", () => {
    const result = validateUploadFiles([fakeFile("gross.pdf", 6 * 1024 * 1024)], opts);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toContain("5 MB");
  });

  it("accepts a file exactly at the size limit", () => {
    const result = validateUploadFiles([fakeFile("genau.pdf", 5 * 1024 * 1024)], opts);
    expect(result).toEqual({ ok: true });
  });

  it("allows any extension when allowedFileTypes is empty", () => {
    const result = validateUploadFiles([fakeFile("anything.xyz", 100)], { ...opts, allowedFileTypes: [] });
    expect(result).toEqual({ ok: true });
  });

  it("checks extension case-insensitively", () => {
    const result = validateUploadFiles([fakeFile("beleg.PDF", 100)], opts);
    expect(result).toEqual({ ok: true });
  });

  it("accounts for files already uploaded in a previous session (cumulative limit)", () => {
    const result = validateUploadFiles([fakeFile("a.pdf", 100), fakeFile("b.pdf", 100)], { ...opts, alreadyUploaded: 1 });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toContain("1 noch möglich");
  });

  it("accepts exactly the remaining capacity after previous uploads", () => {
    const result = validateUploadFiles([fakeFile("a.pdf", 100)], { ...opts, alreadyUploaded: 1 });
    expect(result).toEqual({ ok: true });
  });

  it("allows any number of files when maxFiles is null (unlimited)", () => {
    const files = Array.from({ length: 50 }, (_, i) => fakeFile(`f${i}.pdf`, 100));
    const result = validateUploadFiles(files, { ...opts, maxFiles: null, alreadyUploaded: 1000 });
    expect(result).toEqual({ ok: true });
  });
});
