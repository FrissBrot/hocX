import { describe, expect, it } from "vitest";

import {
  DEFAULT_INCIDENT_FILTERS,
  durationParts,
  heatmapGrid,
  incidentApiQuery,
  incidentFiltersFromParams,
  incidentFiltersToParams,
  incidentLabel,
  parseIncidentId,
  percentChange,
  positionPercent,
  stackedHeights,
} from "./security-incidents";

describe("Vorfälle: URL-Zustand", () => {
  it("liest nur bekannte Codes und eine gültige Vorfall-Nummer", () => {
    const filters = incidentFiltersFromParams(new URLSearchParams("status=closed&severity=critical,bogus,critical&assignee=me&view=board&page=2"));
    expect(filters).toEqual({ status: "closed", severities: ["critical"], assignee: "me", view: "board", page: 2 });
    expect(incidentFiltersFromParams(new URLSearchParams("status=<x>&assignee=alle&page=-1"))).toEqual(DEFAULT_INCIDENT_FILTERS);
    expect(parseIncidentId("42")).toBe(42);
    for (const value of ["0", "-1", "4a", "1e3", "", null, "99999999999999999999"]) expect(parseIncidentId(value)).toBeNull();
  });

  it("schreibt keine Standardwerte und nie einen Suchbegriff in die URL", () => {
    expect(incidentFiltersToParams(DEFAULT_INCIDENT_FILTERS).toString()).toBe("");
    const params = incidentFiltersToParams({ ...DEFAULT_INCIDENT_FILTERS, severities: ["warning", "critical"], status: "new" }, 7);
    expect(params.toString()).toBe("status=new&severity=critical%2Cwarning&incident=7");
  });

  it("baut die API-Abfrage; das Board lädt alle Status, Suche nur mit erlaubten Zeichen", () => {
    const list = incidentApiQuery({ ...DEFAULT_INCIDENT_FILTERS, severities: ["critical"], page: 1 }, { q: " inc-0042 ", limit: 50 });
    expect(Object.fromEntries(list)).toEqual({ status: "open", assignee: "all", severity: "critical", q: "inc-0042", limit: "50", offset: "50" });
    const board = incidentApiQuery({ ...DEFAULT_INCIDENT_FILTERS, view: "board", page: 3 }, { q: "a b'", limit: 100 });
    expect(board.get("status")).toBe("all");
    expect(board.get("offset")).toBe("0");
    expect(board.has("q")).toBe(false);
  });
});

describe("Vorfälle: Anzeige", () => {
  it("Nummer, Dauer und Veränderung", () => {
    expect(incidentLabel(42)).toBe("INC-0042");
    expect(incidentLabel(123456)).toBe("INC-123456");
    expect(durationParts(0)).toEqual({ days: 0, hours: 0, minutes: 0 });
    expect(durationParts(10)).toEqual({ days: 0, hours: 0, minutes: 1 });
    expect(durationParts(26 * 3600 + 5 * 60)).toEqual({ days: 1, hours: 2, minutes: 5 });
    expect(percentChange(438, 31)).toBe(1313);
    expect(percentChange(5, 0)).toBeNull();
  });

  it("Heatmap: 7 × 24 Zellen mit Wurzelstufen", () => {
    const { rows, max } = heatmapGrid([{ dow: 1, hour: 9, count: 400 }, { dow: 7, hour: 23, count: 4 }]);
    expect(rows).toHaveLength(7);
    expect(rows.every((row) => row.length === 24)).toBe(true);
    expect(max).toBe(400);
    expect(rows[0][9].level).toBe(4);
    expect(rows[6][23].level).toBe(1);
    expect(rows[3][3].level).toBe(0);
  });

  it("gestapelte Höhen respektieren ausgeblendete Reihen", () => {
    const points = [
      { start: "a", failures: 4, blocked: 0, challenged: 0, successes: 0 },
      { start: "b", failures: 0, blocked: 0, challenged: 0, successes: 1 },
    ];
    const all = stackedHeights(points, ["failures", "blocked", "challenged", "successes"]);
    expect(all[0].failures).toBe(100);
    expect(all[1].successes).toBe(50);
    const withoutFailures = stackedHeights(points, ["successes"]);
    expect(withoutFailures[0].failures).toBe(0);
    expect(withoutFailures[1].successes).toBe(100);
    expect(positionPercent("2026-11-26T12:00:00Z", "2026-11-26T00:00:00Z", "2026-11-27T00:00:00Z")).toBe(50);
    expect(positionPercent("2026-11-20T00:00:00Z", "2026-11-26T00:00:00Z", "2026-11-27T00:00:00Z")).toBe(0);
  });
});
