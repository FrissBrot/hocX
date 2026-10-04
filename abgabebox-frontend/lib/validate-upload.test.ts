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
    if (!result.ok) {
      expect(result.code).toBe("maxFilesTotal");
      expect(result.params).toEqual({ maxFiles: 2, remaining: 2 });
    }
  });

  it("rejects a disallowed file extension", () => {
    const result = validateUploadFiles([fakeFile("script.exe", 100)], opts);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.code).toBe("unsupportedType");
      expect(result.params).toEqual({ filename: "script.exe" });
    }
  });

  it("rejects a file over the size limit", () => {
    const result = validateUploadFiles([fakeFile("gross.pdf", 6 * 1024 * 1024)], opts);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.code).toBe("fileTooLarge");
      expect(result.params).toEqual({ filename: "gross.pdf", maxFileSizeMb: 5 });
    }
  });

  it("accepts a file exactly at the size limit", () => {
    const result = validateUploadFiles([fakeFile("genau.pdf", 5 * 1024 * 1024)], opts);
    expect(result).toEqual({ ok: true });
  });

  it("rejects unsupported formats even when allowedFileTypes is empty", () => {
    const result = validateUploadFiles([fakeFile("anything.xyz", 100)], { ...opts, allowedFileTypes: [] });
    expect(result.ok).toBe(false);
  });

  it("checks extension case-insensitively", () => {
    const result = validateUploadFiles([fakeFile("beleg.PDF", 100)], opts);
    expect(result).toEqual({ ok: true });
  });

  it("accounts for files already uploaded in a previous session (cumulative limit)", () => {
    const result = validateUploadFiles([fakeFile("a.pdf", 100), fakeFile("b.pdf", 100)], { ...opts, alreadyUploaded: 1 });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.code).toBe("maxFilesTotal");
      expect(result.params).toEqual({ maxFiles: 2, remaining: 1 });
    }
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


it("allows exactly 150 MiB of payload and rejects one additional byte", () => {
  const opts = { maxFiles: null, allowedFileTypes: [], maxFileSizeMb: 100 };
  const files = [{ name: "a.pdf", size: 100 * 1024 ** 2 }, { name: "b.pdf", size: 50 * 1024 ** 2 }] as File[];
  expect(validateUploadFiles(files, opts)).toEqual({ ok: true });
  expect(validateUploadFiles([...files, { name: "c.pdf", size: 1 } as File], opts).ok).toBe(false);
});
it("keeps a hard request count even for unlimited assignments", () => {
  const files = Array.from({ length: 51 }, () => ({ name: "a.pdf", size: 1 }) as File);
  expect(validateUploadFiles(files, { maxFiles: null, allowedFileTypes: [], maxFileSizeMb: 100 }).ok).toBe(false);
});
