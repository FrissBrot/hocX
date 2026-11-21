import { describe, expect, it } from "vitest";

import type { FileOverviewItem, SimilarityGroup } from "@/types/api";
import {
  compareSuggestion,
  compareSummary,
  filmstripRange,
  groupsForItem,
  isDeletable,
  keepAllDecisions,
  nextAfterRemoval,
  setDecision,
  shareExpiryDate,
  shiftPreview,
  toggleDecision,
} from "./viewer-logic";

function image(id: string, source: FileOverviewItem["source"] = "gallery_upload"): FileOverviewItem {
  return { id, source } as FileOverviewItem;
}

const group: SimilarityGroup = {
  best_id: "best",
  images: [image("best"), image("blurry"), image("crop"), image("protocol", "protocol_image")],
};

describe("Löschbarkeit", () => {
  it("lässt nur Direkt-Uploads der Galerie in den Papierkorb", () => {
    expect(isDeletable(image("a"))).toBe(true);
    for (const source of ["protocol_image", "submission_upload", "word_import", "protocol_export"] as const) {
      expect(isDeletable(image("a", source))).toBe(false);
    }
  });
});

describe("Vergleichsentscheid", () => {
  it("schlägt vor: bestes Bild und nicht löschbare behalten, Rest in den Papierkorb", () => {
    expect(compareSuggestion(group)).toEqual({ best: "keep", blurry: "trash", crop: "trash", protocol: "keep" });
    expect(compareSummary(group, compareSuggestion(group))).toEqual({ keep: 2, trash: 2, trashIds: ["blurry", "crop"] });
  });

  it("ohne Vorschlag bleibt alles, «Alle behalten» ebenso", () => {
    expect(Object.values(compareSuggestion(group, false))).toEqual(["keep", "keep", "keep", "keep"]);
    expect(compareSummary(group, keepAllDecisions(group))).toEqual({ keep: 4, trash: 0, trashIds: [] });
  });

  it("schaltet löschbare Bilder um, nicht löschbare bleiben immer", () => {
    let decisions = keepAllDecisions(group);
    decisions = toggleDecision(decisions, group.images[1]);
    expect(decisions.blurry).toBe("trash");
    decisions = toggleDecision(decisions, group.images[1]);
    expect(decisions.blurry).toBe("keep");
    expect(toggleDecision(decisions, group.images[3]).protocol).toBe("keep");
    expect(setDecision(decisions, group.images[3], "trash")).toBe(decisions);
    // Ein veralteter «trash»-Entscheid für ein gesperrtes Bild löscht es trotzdem nicht.
    expect(compareSummary(group, { ...decisions, protocol: "trash" }).trashIds).toEqual([]);
  });

  it("springt nach dem Löschen auf das aktuelle, sonst das beste, sonst ein übriges Bild", () => {
    expect(nextAfterRemoval("best", ["blurry"], group)).toBe("best");
    expect(nextAfterRemoval("blurry", ["blurry", "crop"], group)).toBe("best");
    expect(nextAfterRemoval("best", ["best", "blurry"], group)).toBe("crop");
    expect(nextAfterRemoval("x", ["x"], null)).toBeNull();
  });

  it("zeigt nur ungeprüfte Gruppen mit dem Foto, Duplikate zuerst", () => {
    const series: SimilarityGroup = { best_id: "best", images: [image("best"), image("other")] };
    const small: SimilarityGroup = { best_id: "solo", images: [image("solo")] };
    expect(groupsForItem("best", [group], [series, small], new Set()).map((entry) => entry.key)).toEqual(["duplicate:best", "series:best"]);
    expect(groupsForItem("best", [group], [series], new Set(["duplicate:best"])).map((entry) => entry.key)).toEqual(["series:best"]);
    expect(groupsForItem("solo", [], [small], new Set())).toEqual([]);
  });
});

describe("Aufnahmedatum verschieben: Vorschau", () => {
  const base = { capture_corrected_at: null, capture_corrected_has_time: false, exif_taken_at: null, estimated_taken_on: null };

  it("rechnet mit der Kamerazeit des EXIF-Datums, über Mitternacht und Monatsgrenzen", () => {
    expect(shiftPreview({ ...base, exif_taken_at: "2001-01-01T00:05:00Z" }, -1, 2)).toEqual({ date: "2000-12-31", time: "02:05" });
    expect(shiftPreview({ ...base, exif_taken_at: "2025-07-12T14:32:00" }, 0, 10)).toEqual({ date: "2025-07-13", time: "00:32" });
  });

  it("ignoriert Sommerzeit-Wechsel (Kamerazeit hat keine Zeitzone)", () => {
    expect(shiftPreview({ ...base, exif_taken_at: "2025-03-30T01:30:00Z" }, 0, 1)).toEqual({ date: "2025-03-30", time: "02:30" });
  });

  it("nimmt die Korrektur vor EXIF und zeigt ohne Uhrzeit nur den Tag", () => {
    const corrected = { ...base, exif_taken_at: "2001-01-01T00:05:00Z", capture_corrected_at: "2023-07-14T12:00:00Z", capture_corrected_has_time: false };
    expect(shiftPreview(corrected, 1, 0)).toEqual({ date: "2023-07-15", time: null });
    expect(shiftPreview(corrected, 1, 0)?.noTimeUnchanged).toBeUndefined();
  });

  it("verschiebt Fotos ohne Uhrzeit nur um ganze Tage (wie whole_shift_days im Backend)", () => {
    const corrected = { ...base, capture_corrected_at: "2023-07-14T12:00:00Z", capture_corrected_has_time: false };
    // Stunden allein wirken nicht: unverändert – keine Uhrzeit
    expect(shiftPreview(corrected, 0, 12)).toEqual({ date: "2023-07-14", time: null, noTimeUnchanged: true });
    expect(shiftPreview(corrected, 0, -13)).toEqual({ date: "2023-07-14", time: null, noTimeUnchanged: true });
    // 1 Tag − 2 h ergibt keinen ganzen Tag
    expect(shiftPreview(corrected, 1, -2)).toEqual({ date: "2023-07-14", time: null, noTimeUnchanged: true });
    // −30 h → −1 Tag, 1 Tag + 5 h → +1 Tag
    expect(shiftPreview(corrected, 0, -30)).toEqual({ date: "2023-07-13", time: null });
    expect(shiftPreview(corrected, 1, 5)).toEqual({ date: "2023-07-15", time: null });
  });

  it("verschiebt ein geschätztes Datum, aber nie das Uploaddatum", () => {
    expect(shiftPreview({ ...base, estimated_taken_on: "1998-08-01" }, -3, 0)).toEqual({ date: "1998-07-29", time: null });
    expect(shiftPreview(base, 1, 0)).toBeNull();
  });
});

describe("Freigabelink und Filmstreifen", () => {
  it("rechnet das Ablaufdatum in Tagen ab heute, unbegrenzt = null", () => {
    const today = new Date(2026, 11, 28);
    expect(shareExpiryDate("7", today)).toBe("2027-01-04");
    expect(shareExpiryDate("30", today)).toBe("2027-01-27");
    expect(shareExpiryDate("never", today)).toBeNull();
  });

  it("zeigt einen Ausschnitt rund um das aktuelle Foto", () => {
    expect(filmstripRange(0, 10)).toEqual([0, 10]);
    expect(filmstripRange(500, 1000, 30)).toEqual([470, 531]);
    expect(filmstripRange(999, 1000, 30)).toEqual([939, 1000]);
  });
});
