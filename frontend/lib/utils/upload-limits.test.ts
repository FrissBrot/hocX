import { describe, expect, it } from "vitest";
import { photoUploadProblem, PHOTO_MAX_BYTES, PHOTO_ZIP_MAX_BYTES } from "./upload-limits";
const file = (name: string, size: number) => ({ name, size }) as File;

describe("Foto-Uploadgrenzen", () => {
  it("akzeptiert ein ZIP mit exakt 10 GiB, aber keinen weiteren Byte", () => {
    expect(photoUploadProblem([file("photos.zip", PHOTO_ZIP_MAX_BYTES)], new Set())).toBeNull();
    expect(photoUploadProblem([file("photos.zip", PHOTO_ZIP_MAX_BYTES + 1)], new Set())).toContain("10 GiB");
  });
  it("prüft Bilder und Live-Clips getrennt", () => {
    expect(photoUploadProblem([file("photo.jpg", PHOTO_MAX_BYTES)], new Set())).toBeNull();
    expect(photoUploadProblem([file("photo.jpg", PHOTO_MAX_BYTES + 1)], new Set())).toContain("100 MiB");
    expect(photoUploadProblem([file("photo.mov", 31 * 1024 ** 2)], new Set([0]))).toContain("30 MiB");
  });
  it("prüft Gesamtgrösse und Anzahl der Auswahl vor dem Senden", () => {
    // Mehr als ein Auftrag fasst, wird automatisch in mehrere Aufträge geteilt.
    expect(photoUploadProblem([file("a.zip", 6 * 1024 ** 3), file("b.zip", 6 * 1024 ** 3)], new Set())).toBeNull();
    expect(photoUploadProblem(Array.from({ length: 51 }, () => file("a.jpg", 1)), new Set())).toBeNull();
    expect(photoUploadProblem(Array.from({ length: 2001 }, () => file("a.jpg", 1)), new Set())).toContain("2000 Dateien");
    expect(photoUploadProblem(Array.from({ length: 6 }, (_, i) => file(`${i}.zip`, 9 * 1024 ** 3)), new Set())).toContain("50 GiB");
  });
});
