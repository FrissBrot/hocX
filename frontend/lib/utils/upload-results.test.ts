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
    expect(batches.map((batch) => batch.filter((index) => index !== 119).length)).toEqual([50, 50, 19]);
    expect(batches[0]).toContain(119);
    expect(batches.flat().sort((a, b) => a - b)).toEqual(sizes.map((_, index) => index));
  });

  it("teilt auch nach Grösse", () => {
    expect(splitIntoBatches([6, 6, 6], new Map(), 50, 10, (size) => size)).toEqual([[0], [1], [2]]);
  });
});
