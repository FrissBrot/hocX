import { describe, expect, it } from "vitest";

import de from "@/messages/de/photos.json";

import { formatPlaceLabel, formatSearchHit, hitShortLabel, PhotoPlace, placeFilterQuery, radiusForKind, regionLabel, widenRadius } from "./places";

// Einfache ICU-freie Übersetzung für die Hilfsfunktionen (Platzhalter {x} ersetzen)
function t(key: string, values: Record<string, string | number> = {}): string {
  const raw = key.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown>)?.[part], de.places) as string;
  return raw.replace(/\{(\w+)\}/g, (_, name: string) => String(values[name] ?? ""));
}

function place(overrides: Partial<PhotoPlace> = {}): PhotoPlace {
  return {
    key: "sn:1", name: null, kind: null, locality_name: "Kandersteg", locality_kind: "village", admin1_code: "BE",
    country_code: "CH", near: false, source: "gps", distance_m: null, ...overrides,
  };
}

describe("Foto-Standorte: Beschriftung", () => {
  it("präziser Ort mit Ortschaft und Kanton", () => {
    expect(formatPlaceLabel(place({ name: "Blüemlisalphütte", kind: "hut", near: true }), t, "de")).toBe("Nähe Blüemlisalphütte, Kandersteg BE");
  });

  it("nur Ortschaft, im Dorf ohne «Nähe», ausserhalb mit", () => {
    expect(formatPlaceLabel(place(), t, "de")).toBe("Kandersteg BE");
    expect(formatPlaceLabel(place({ near: true }), t, "de")).toBe("Nähe Kandersteg BE");
  });

  it("im Ausland mit Land in der UI-Sprache statt Kanton", () => {
    const label = formatPlaceLabel(place({ locality_name: "Chamonix-Mont-Blanc", admin1_code: "84", country_code: "FR" }), t, "de");
    expect(label).toBe("Chamonix-Mont-Blanc, Frankreich");
    expect(regionLabel("Chamonix-Mont-Blanc", "84", "FR", "en")).toBe("Chamonix-Mont-Blanc, France");
  });

  it("ohne Ort nichts", () => {
    expect(formatPlaceLabel(null, t, "de")).toBeNull();
    expect(formatPlaceLabel(place({ locality_name: null, country_code: null }), t, "de")).toBeNull();
  });

  it("Treffer der Ortssuche mit Art und Umgebung", () => {
    const hit = { key: "sn:1", name: "Blüemlisalphütte SAC", kind: "hut", admin1_code: "BE", admin1_name: "Bern", country_code: "CH", locality_name: "Kandersteg", radius_km: 2 };
    expect(formatSearchHit(hit, t, "de")).toBe("Blüemlisalphütte SAC · Hütte · Kandersteg BE");
    const village = { ...hit, key: "gn:1", name: "Kandersteg", kind: "village", locality_name: null, radius_km: 5 };
    expect(formatSearchHit(village, t, "de")).toBe("Kandersteg · Dorf · BE");
    expect(hitShortLabel(village, "de")).toBe("Kandersteg BE");
    expect(formatSearchHit({ ...village, kind: "unknown" }, t, "de")).toBe("Kandersteg · Ort · BE");
  });
});

describe("Foto-Standorte: Umkreis", () => {
  it("Radius je Ortsart und «+10 km» bis höchstens 200 km", () => {
    expect([radiusForKind("hut"), radiusForKind("village"), radiusForKind("city"), radiusForKind(null)]).toEqual([2, 5, 20, 5]);
    const filter = { key: "gn:1", label: "Kandersteg BE", radiusKm: 5, baseRadiusKm: 5 };
    expect(widenRadius(filter).radiusKm).toBe(15);
    expect(widenRadius({ ...filter, radiusKm: 195 }).radiusKm).toBe(200);
    expect(placeFilterQuery(filter)).toBe("near=gn%3A1&near_km=5");
    expect(placeFilterQuery(null)).toBe("");
  });
});
