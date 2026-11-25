import { describe, expect, it } from "vitest";

import {
  apiErrorCode,
  chunk,
  cloudSelectionMode,
  isPhotosPickerUri,
  photosPickerUrl,
  pickedFileIds,
  pickerJobId,
  wizardUrl,
  cleanRule,
  importProgress,
  isHiddenPath,
  moveItem,
  newRule,
  normalizeImportPath,
  pathedFromInput,
  isCloudSource,
  readCloudReturn,
  uploadBatches,
  type ImportJob,
} from "./file-import";

function fileOf(name: string, size: number, relative?: string): File {
  const file = new File([new Uint8Array(size)], name);
  if (relative) Object.defineProperty(file, "webkitRelativePath", { value: relative });
  return file;
}

describe("file-import helpers", () => {
  it("keeps relative folder paths and drops system files", () => {
    const files = [fileOf("a.jpg", 1, "Verein/Fotos/a.jpg"), fileOf(".DS_Store", 1, "Verein/.DS_Store"), fileOf("x", 1, "Verein/__MACOSX/x")];
    expect(pathedFromInput(files).map((entry) => entry.path)).toEqual(["Verein/Fotos/a.jpg"]);
    expect(isHiddenPath("a/Thumbs.db")).toBe(true);
    expect(isHiddenPath("a/b.pdf")).toBe(false);
  });

  it("normalizes paths like the backend", () => {
    expect(normalizeImportPath("Ordner\\Unter\\./a.pdf")).toBe("Ordner/Unter/a.pdf");
    expect(normalizeImportPath("../x/../a.pdf")).toBe("x/a.pdf");
    expect(normalizeImportPath("Café/a.jpg")).toBe("Café/a.jpg");
  });

  it("splits uploads by file count and bytes", () => {
    const files = [1, 2, 3, 4, 5].map((n) => ({ path: `p${n}`, file: fileOf(`f${n}`, n * 10) }));
    expect(uploadBatches(files, 2, 1000).map((batch) => batch.length)).toEqual([2, 2, 1]);
    expect(uploadBatches(files, 10, 35).map((batch) => batch.map((entry) => entry.path))).toEqual([["p1", "p2"], ["p3"], ["p4"], ["p5"]]);
    expect(chunk([1, 2, 3], 2)).toEqual([[1, 2], [3]]);
  });

  it("sends only the fields of the chosen action", () => {
    const rule = newRule("set_date");
    rule.action.tags = ["alt"];
    rule.action.date = "2019-07-01";
    rule.match.path_glob = "  *.jpg ";
    const cleaned = cleanRule(rule);
    expect(cleaned.action).toEqual({ type: "set_date", date: "2019-07-01" });
    expect(cleaned.match.path_glob).toBe("*.jpg");
    expect(cleaned.match.folder).toBeNull();
    const album = cleanRule({ ...newRule("add_to_album"), action: { type: "add_to_album", album_id: "id-1", album_name: "Neu" } });
    expect(album.action).toEqual({ type: "add_to_album", album_id: "id-1", album_name: null });
  });

  it("creates unique rule ids and moves rules", () => {
    expect(newRule().id).not.toBe(newRule().id);
    expect(moveItem(["a", "b", "c"], 0, 2)).toEqual(["b", "c", "a"]);
    expect(moveItem(["a", "b"], 0, 5)).toEqual(["a", "b"]);
  });

  it("computes progress from item counts", () => {
    const job = { counts: { imported: 2, duplicate: 1, failed: 1, queued: 4, skipped: 10 } } as unknown as ImportJob;
    expect(importProgress(job)).toBe(50);
    expect(importProgress({ counts: {} } as unknown as ImportJob)).toBe(0);
  });

  it("reads the error code of an api error", () => {
    expect(apiErrorCode({ detail: { code: "import_active" } })).toBe("import_active");
    expect(apiErrorCode(new Error("x"))).toBeNull();
  });
});

describe("Rückkehr vom Cloud-Anbieter", () => {
  it("liest Auftrag, Fehler und Abschluss-Token (nur aus dem Fragment)", () => {
    expect(readCloudReturn("?job=j1&cloud_error=cancelled", "")).toEqual({ job: "j1", error: "cancelled", notice: null, finish: null });
    expect(readCloudReturn("?job=j1&cloud_finish=nein", "#cloud_finish=abc")).toEqual({ job: "j1", error: null, notice: null, finish: "abc" });
    expect(readCloudReturn("?cloud_notice=admin_consent_done", "")).toMatchObject({ notice: "admin_consent_done" });
  });

  it("erkennt API-Quellen", () => {
    expect(isCloudSource("microsoft")).toBe(true);
    expect(isCloudSource("zip")).toBe(false);
    expect(isCloudSource("folder")).toBe(false);
  });
});

describe("Google-Auswahl", () => {
  it("erkennt die Auswahl-Art eines Anbieters", () => {
    expect(cloudSelectionMode(null)).toBe("tree");
    expect(cloudSelectionMode({ key: "google_drive", tiers: [], default_tier: "basic", info: { selection: "google_picker" } })).toBe("google_picker");
    expect(cloudSelectionMode({ key: "google_photos", tiers: [], default_tier: "basic", info: { selection: "photos_picker" } })).toBe("photos_picker");
    expect(cloudSelectionMode({ key: "microsoft", tiers: [], default_tier: "basic", info: { selection: "other" } })).toBe("tree");
  });

  it("nimmt nur gültige Datei-IDs aus der Picker-Antwort", () => {
    const docs = [
      { id: "abc_DEF-1", mimeType: "image/jpeg" },
      { id: "abc_DEF-1", mimeType: "image/jpeg" },
      { id: "folder1", mimeType: "application/vnd.google-apps.folder" },
      { id: "../x?y", mimeType: "text/plain" },
      { id: 5 },
      { id: "doc2", mimeType: "application/vnd.google-apps.document" },
    ];
    expect(pickedFileIds(docs, 200)).toEqual(["abc_DEF-1", "doc2"]);
    expect(pickedFileIds(docs, 1)).toEqual(["abc_DEF-1"]);
  });

  it("liest nur eine gültige Auftrags-ID und springt relativ zurück", () => {
    const id = "0194f1c2-1111-7aaa-8bbb-123456789abc";
    expect(pickerJobId(`?job=${id}`)).toBe(id);
    expect(pickerJobId("?job=https://evil.example")).toBeNull();
    expect(wizardUrl(id)).toBe(`/files/import?job=${id}`);
    expect(wizardUrl(null)).toBe("/files/import");
  });

  it("öffnet nur Auswahlseiten von Google Fotos", () => {
    const origin = "https://verein.hocx.test";
    expect(isPhotosPickerUri("https://photos.google.com/picker/abc", origin)).toBe(true);
    expect(isPhotosPickerUri("http://photos.google.com/picker/abc", origin)).toBe(false);
    expect(isPhotosPickerUri("https://photos.google.com.evil.example/x", origin)).toBe(false);
    expect(isPhotosPickerUri("javascript:alert(1)", origin)).toBe(false);
    expect(isPhotosPickerUri(`${origin}/api/cloud-import/fake-google/photos/s1`, origin)).toBe(true);
    expect(isPhotosPickerUri(`${origin}/files`, origin)).toBe(false);
  });

  it("hängt /autoclose genau einmal an", () => {
    expect(photosPickerUrl("https://photos.google.com/picker/abc")).toBe("https://photos.google.com/picker/abc/autoclose");
    expect(photosPickerUrl("https://photos.google.com/picker/abc/autoclose")).toBe("https://photos.google.com/picker/abc/autoclose");
  });
});
