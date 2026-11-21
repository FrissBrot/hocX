import { describe, expect, it } from "vitest";

import { AUDIT_URL_CONFIG, auditApiQuery, auditDiff, groupByDay, relativeDay, selectedAreas, stepSelection, toggleArea, type AuditFilters } from "./audit-log";
import { serverTableStateFromParams, serverTableUrlQuery } from "./use-server-table";

const base: AuditFilters = { ...AUDIT_URL_CONFIG.defaults };

describe("Audit-Log (Design 1.5.1)", () => {
  it("gruppiert nach Kalendertag, zählt Fehlschläge, Reihenfolge bleibt", () => {
    const groups = groupByDay([
      { id: 1, created_at: new Date(2026, 10, 21, 9, 0).toISOString(), outcome: "success" },
      { id: 2, created_at: new Date(2026, 10, 21, 7, 0).toISOString(), outcome: "failure" },
      { id: 3, created_at: new Date(2026, 10, 20, 23, 0).toISOString(), outcome: "success" },
    ]);
    expect(groups.map((group) => group.entries.map((entry) => entry.id))).toEqual([[1, 2], [3]]);
    expect(groups.map((group) => group.failures)).toEqual([1, 0]);
    const now = new Date(2026, 10, 21, 12, 0);
    expect(relativeDay(groups[0].date, now)).toBe("today");
    expect(relativeDay(groups[1].date, now)).toBe("yesterday");
    expect(relativeDay(new Date(2026, 10, 1), now)).toBeNull();
  });

  it("J/K: nächster und vorheriger Eintrag, ohne Auswahl der erste, an den Rändern stehen bleiben", () => {
    expect(stepSelection([5, 4, 3], null, 1)).toBe(5);
    expect(stepSelection([5, 4, 3], 5, 1)).toBe(4);
    expect(stepSelection([5, 4, 3], 3, 1)).toBe(3);
    expect(stepSelection([5, 4, 3], 5, -1)).toBe(5);
    expect(stepSelection([], null, 1)).toBeNull();
  });

  it("Vorher/Nachher nur, wenn beides in den Details steht", () => {
    expect(auditDiff({ field: "fine_relevant", before: false, after: true })).toEqual({ field: "fine_relevant", before: "false", after: "true" });
    expect(auditDiff({ before: "a" })).toBeNull();
    expect(auditDiff({ field: "x" })).toBeNull();
    expect(auditDiff(null)).toBeNull();
  });

  it("Bereiche als Codes in der URL, als Kategorien an die API", () => {
    const filters = { ...base, area: toggleArea(base, "privacy") };
    expect(filters.area).toBe("privacy");
    expect(toggleArea({ area: "privacy" }, "auth")).toBe("auth,privacy");
    expect(selectedAreas({ area: "auth,unbekannt" })).toEqual(["auth"]);
    const api = auditApiQuery(filters);
    expect(api.getAll("category")).toEqual(expect.arrayContaining(["personal_data", "public_link"]));
    expect(api.get("area")).toBeNull();
  });

  it("URL nimmt nur gültige IDs/Codes an und lässt Standards weg", () => {
    const state = serverTableStateFromParams(new URLSearchParams("range=1y&actor_id=anna@example.com&source=ZZ&area=auth&outcome=failure"), AUDIT_URL_CONFIG);
    expect(state.filters.range).toBe("7d");
    expect(state.filters.actor_id).toBe("");
    expect(state.filters.source).toBe("");
    expect(state.filters.area).toBe("auth");
    expect(serverTableUrlQuery(state, AUDIT_URL_CONFIG).toString()).toBe("outcome=failure&area=auth");
  });
});
