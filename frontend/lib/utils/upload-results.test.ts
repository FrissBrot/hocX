import { describe, expect, it } from "vitest";

import { countUploadResults, normalizeResult, resultsFromLegacyJob, splitIntoBatches } from "./upload-results";

describe("Upload-Ergebnisse", () => {
  it("zählt jede Datei genau einmal - Metadaten ergänzt ist nicht zusätzlich übersprungen", () => {
    const counts = countUploadResults([
      { name: "a", status: "uploaded" },
      { name: "b", status: "skipped" },
      { name: "c", status: "metadata_updated", applied: ["estimated_taken_on"] },
      { name: "d", status: "failed" },
      { name: "e", status: "uploaded" },
    ]);
    expect(counts).toEqual({ total: 5, uploaded: 2, skipped: 1, metadataUpdated: 1, failed: 1 });
  });

  it("behauptet keine Ergänzung ohne bestätigte Felder", () => {
    expect(normalizeResult({ name: "x", status: "metadata_updated", applied: [] }).status).toBe("skipped");
    expect(normalizeResult({ name: "x", status: "metadata_updated", applied: ["gps"] }).status).toBe("metadata_updated");
  });

  it("leitet Ergebnisse älterer Aufträge aus Fehlertexten ab, Hinweise zählen nicht als Fehler", () => {
    expect(resultsFromLegacyJob(["neu.jpg"], [
      "alt.jpg: Exaktes Duplikat – bereits vorhanden, nicht erneut gespeichert.",
      "neu.jpg: Hinweis - ähnelt einem bereits im Mandanten hochgeladenen Bild",
      "kaputt.jpg: kein unterstütztes Bildformat",
    ]).map((result) => [result.name, result.status])).toEqual([["neu.jpg", "uploaded"], ["alt.jpg", "skipped"], ["kaputt.jpg", "failed"]]);
  });

  it("teilt grosse Auswahlen (Ordner) in Aufträge und hält Live-Photo-Paare zusammen", () => {
    const sizes = Array.from({ length: 120 }, () => 1);
    const batches = splitIntoBatches(sizes, new Map([[49, 119]]), 50, 1000, (size) => size);
    // Der Clip zählt mit (Server prüft alle Multipart-Dateien): Bild 49 + Clip passen nicht mehr
    // in den ersten Auftrag und wandern gemeinsam in den zweiten.
    expect(batches.map((batch) => batch.length)).toEqual([49, 50, 21]);
    expect(batches[1]).toEqual(expect.arrayContaining([49, 119]));
    expect(batches.flat().sort((a, b) => a - b)).toEqual(sizes.map((_, index) => index));
  });

  it("überschreitet mit Live-Photo-Clips nie das Server-Limit je Auftrag (IMGMETA-001)", () => {
    // 60 Live Photos: Bilder 0-59, Clips 60-119.
    const sizes = Array.from({ length: 120 }, () => 1);
    const clipOf = new Map(Array.from({ length: 60 }, (_, index) => [index, index + 60] as [number, number]));
    const batches = splitIntoBatches(sizes, clipOf, 50, 1000, (size) => size);
    for (const batch of batches) expect(batch.length).toBeLessThanOrEqual(50);
    for (const [photo, clip] of clipOf) expect(batches.find((batch) => batch.includes(photo))).toContain(clip);
    expect(batches.map((batch) => batch.length)).toEqual([50, 50, 20]);
    expect(batches.flat().sort((a, b) => a - b)).toEqual(sizes.map((_, index) => index));
  });

  it("teilt auch nach Grösse", () => {
    expect(splitIntoBatches([6, 6, 6], new Map(), 50, 10, (size) => size)).toEqual([[0], [1], [2]]);
  });
});
