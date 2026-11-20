import { describe, expect, it } from "vitest";

import type { ElementDefinitionBlock } from "@/types/api";

import { changedLabel, contentTypeIds, titleSegments } from "./element-list-utils";

const t = (key: string, values?: Record<string, string | number | Date>) =>
  values ? `${key}:${Object.values(values).join(",")}` : key;

describe("titleSegments", () => {
  it("trennt Platzhalter vom Text", () => {
    expect(titleSegments("Programm {cycle_year_start}/{cycle_year_end} neu")).toEqual([
      { text: "Programm ", placeholder: false },
      { text: "{cycle_year_start}", placeholder: true },
      { text: "/", placeholder: false },
      { text: "{cycle_year_end}", placeholder: true },
      { text: " neu", placeholder: false },
    ]);
  });

  it("lässt Titel ohne Platzhalter und geschweifte Klammern ohne Namen unverändert", () => {
    expect(titleSegments("Begrüssung")).toEqual([{ text: "Begrüssung", placeholder: false }]);
    expect(titleSegments("A {} B {1x}")).toEqual([{ text: "A {} B {1x}", placeholder: false }]);
  });
});

describe("contentTypeIds", () => {
  it("liefert eindeutige Typen in Blockreihenfolge", () => {
    const blocks = [
      { element_type_id: 2, sort_index: 20 },
      { element_type_id: 1, sort_index: 10 },
      { element_type_id: 2, sort_index: 30 },
    ] as ElementDefinitionBlock[];
    expect(contentTypeIds(blocks)).toEqual([1, 2]);
  });
});

describe("changedLabel", () => {
  const now = new Date("2026-11-20T10:00:00Z");

  it("zählt Kalendertage in der App-Zeitzone", () => {
    expect(changedLabel("2026-11-20T06:00:00Z", t, "de", now)).toBe("changed.today");
    // 23:30 UTC am 19. ist in Zürich schon der 20.
    expect(changedLabel("2026-11-19T23:30:00Z", t, "de", now)).toBe("changed.today");
    expect(changedLabel("2026-11-19T12:00:00Z", t, "de", now)).toBe("changed.yesterday");
    expect(changedLabel("2026-11-17T12:00:00Z", t, "de", now)).toBe("changed.daysAgo:3");
    expect(changedLabel("2026-11-07T12:00:00Z", t, "de", now)).toBe("changed.daysAgo:13");
  });

  it("zeigt ältere Änderungen als Datum, mit Jahr nur ausserhalb des laufenden Jahres", () => {
    expect(changedLabel("2026-09-12T12:00:00Z", t, "de", now)).toMatch(/^changed\.on:12\. Sep/);
    expect(changedLabel("2025-09-12T12:00:00Z", t, "de", now)).toMatch(/^changed\.on:12\. Sep.*2025$/);
  });
});
