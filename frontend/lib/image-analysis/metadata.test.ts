import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { analyzeFile } from "./analyze";
import { detectImageFormat, gpsFromIfd, parseCaptureDateTime, parseImageMetadata, parseOffset } from "./metadata";

// Testbilder mit Pillow erzeugt (siehe backend/tests/image_fixtures.py) - echte Dateien statt
// von Hand gebauter Bytes, damit der Browser-Parser gegen dieselben Formate läuft wie der Server.
function fixture(name: string): Uint8Array {
  return new Uint8Array(readFileSync(join(__dirname, "__fixtures__", name)));
}

function asFile(name: string, bytes: Uint8Array): File {
  return new File([bytes], name);
}

describe("Bildformat-Erkennung", () => {
  it.each([
    ["full.jpg", "jpeg"], ["full.png", "png"], ["full.webp", "webp"], ["full.tiff", "tiff"], ["full.heic", "heic"], ["plain.gif", "gif"],
  ])("%s ist %s", (name, format) => {
    expect(detectImageFormat(fixture(name))).toBe(format);
  });

  it("unbekannte Bytes sind kein Bild", () => {
    expect(detectImageFormat(new TextEncoder().encode("definitely not an image"))).toBeNull();
  });
});

describe("Metadaten aus echten Dateien", () => {
  it("JPEG: Aufnahmedatum mit Offset, Kamera, Ausrichtung und GPS auf der Süd-/Westhalbkugel", () => {
    const metadata = parseImageMetadata(fixture("full.jpg"), "jpeg");
    expect(metadata.taken_at).toBe("2023-07-14T10:30:05");
    expect(metadata.taken_offset).toBe("+02:00");
    expect(metadata.camera_make).toBe("Apple");
    expect(metadata.camera_model).toBe("iPhone 15");
    expect(metadata.orientation).toBe(6);
    expect(metadata.gps?.latitude).toBeCloseTo(-33.8688, 4);
    expect(metadata.gps?.longitude).toBeCloseTo(-70.6693, 4);
    expect(metadata.gps?.altitude_m).toBeCloseTo(-28.5, 1);
    expect(metadata.gps?.direction_deg).toBeCloseTo(123.45, 2);
    expect([metadata.width, metadata.height]).toEqual([40, 30]);
  });

  it.each([
    ["full.png", "png", "2022-01-02T03:04:05", 46.5, 7.25],
    ["full.webp", "webp", "2021-05-06T07:08:09", 10.5, -20.25],
    ["full.heic", "heic", "2024-06-01T18:45:00", 46.2, -6.1],
  ] as const)("%s: Datum und GPS", (name, format, takenAt, latitude, longitude) => {
    const metadata = parseImageMetadata(fixture(name), format);
    expect(metadata.taken_at).toBe(takenAt);
    expect(metadata.gps?.latitude).toBeCloseTo(latitude, 4);
    expect(metadata.gps?.longitude).toBeCloseTo(longitude, 4);
  });

  it("TIFF: Datum und Hersteller", () => {
    const metadata = parseImageMetadata(fixture("full.tiff"), "tiff");
    expect(metadata.taken_at).toBe("2020-02-29T23:59:59");
    expect(metadata.camera_make).toBe("Nikon");
  });

  it("ein von hocX exportiertes Schätzdatum gilt nicht als echtes Aufnahmedatum", () => {
    const metadata = parseImageMetadata(fixture("exported-estimate.jpg"), "jpeg");
    expect(metadata.taken_at).toBeUndefined();
    expect(metadata.estimated_taken_on).toBe("1987-04-12");
  });
});

describe("Werte prüfen", () => {
  it("EXIF-Datum ohne Zeitzone bleibt lokale Kamerazeit, Unplausibles wird verworfen", () => {
    const now = new Date("2026-10-15T12:00:00Z");
    expect(parseCaptureDateTime("2024:05:01 13:14:15", now)).toBe("2024-05-01T13:14:15");
    expect(parseCaptureDateTime("0000:00:00 00:00:00", now)).toBeUndefined();
    expect(parseCaptureDateTime("2023:02:30 10:00:00", now)).toBeUndefined();
    expect(parseCaptureDateTime("1800:01:01 00:00:00", now)).toBeUndefined();
    expect(parseCaptureDateTime("2027:01:01 00:00:00", now)).toBeUndefined();
    expect(parseOffset("+02:00")).toBe("+02:00");
    expect(parseOffset("+0530")).toBe("+05:30");
    expect(parseOffset("+99:00")).toBeUndefined();
  });

  it("GPS: Süd/West negativ, 0/0 und Bereichsfehler verworfen", () => {
    expect(gpsFromIfd(new Map<number, number | number[] | string>([[1, "N"], [2, [47, 22, 36.84]], [3, "E"], [4, [8, 32, 30.12]]]))).toMatchObject({ latitude: 47.3769, longitude: 8.5417 });
    expect(gpsFromIfd(new Map<number, number | number[] | string>([[1, "S"], [2, [33, 52, 7.68]], [3, "W"], [4, [70, 40, 9.48]]]))?.latitude).toBeLessThan(0);
    expect(gpsFromIfd(new Map<number, number | number[] | string>([[1, "N"], [2, [0, 0, 0]], [3, "E"], [4, [0, 0, 0]]]))).toBeUndefined();
    expect(gpsFromIfd(new Map<number, number | number[] | string>([[1, "N"], [2, [95, 0, 0]], [3, "E"], [4, [1, 0, 0]]]))).toBeUndefined();
  });
});

describe("analyzeFile", () => {
  it("berechnet SHA-256 über die Originalbytes und meldet ein vorhandenes Datum", async () => {
    const bytes = fixture("full.jpg");
    const result = await analyzeFile(asFile("a.jpg", bytes));
    const expected = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), (b) => b.toString(16).padStart(2, "0")).join("");
    expect(result.sha256).toBe(expected);
    expect(result.analysis).toBe("ok");
    expect(result.captureDate).toBe("present");
  });

  it("unterscheidet 'kein Datum' von 'nicht prüfbar'", async () => {
    expect((await analyzeFile(asFile("ohne.jpg", fixture("plain.jpg")))).captureDate).toBe("missing");
    expect((await analyzeFile(asFile("bild.gif", fixture("plain.gif")))).captureDate).toBe("missing");
    const unknown = await analyzeFile(asFile("komisch.jpg", new TextEncoder().encode("kein Bildformat, aber hashbar")));
    expect(unknown.captureDate).toBe("unknown");
    expect(unknown.analysis).toBe("unsupported");
    expect(unknown.sha256).toHaveLength(64);
  });

  it("ZIPs und Live-Clips prüft nur der Server", async () => {
    const zip = await analyzeFile(asFile("album.zip", new Uint8Array([0x50, 0x4b, 3, 4])));
    expect(zip).toMatchObject({ kind: "zip", sha256: null, captureDate: "unknown" });
    expect((await analyzeFile(asFile("IMG_1.MOV", new Uint8Array(8)))).kind).toBe("clip");
  });

  it("defekte Metadaten führen nie zu 'Datum fehlt'", async () => {
    // JPEG-Kopf mit kaputtem APP1-Segment.
    const broken = new Uint8Array([0xff, 0xd8, 0xff, 0xe1, 0xff, 0xff, 0x45, 0x78, 0x69, 0x66, 0, 0, 0x49, 0x49]);
    const result = await analyzeFile(asFile("kaputt.jpg", broken));
    expect(result.captureDate === "unknown" || result.captureDate === "missing").toBe(true);
    expect(result.sha256).toHaveLength(64);
  });
});
