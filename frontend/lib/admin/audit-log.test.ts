import { describe, expect, it } from "vitest";

import {
  AUDIT_URL_CONFIG,
  activeAuditView,
  applyAuditView,
  auditApiQuery,
  auditDiff,
  groupByDay,
  parseAuditTokens,
  relativeDay,
  selectedAreas,
  stepSelection,
  toggleArea,
  type AuditFilters,
} from "./audit-log";
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

describe("Audit-Log Ansichten und Token-Suche (1.6)", () => {
  const aliases = { person: ["person"], tenant: ["mandant"], source: ["quelle"], action: ["aktion"], verb: ["vorgang"] };
  const verbs = { "gelöscht": "deleted", angesehen: "viewed" } as const;

  it("erkennt die aktive Ansicht und wendet sie an (Zeitraum/Mandant bleiben)", () => {
    const filters = { ...base, range: "30d", tenant_id: "0193a6f0-0000-7000-8000-000000000001", source: "abcd" };
    expect(activeAuditView(filters, AUDIT_URL_CONFIG.defaults)).toBeNull();
    const applied = applyAuditView(filters, "deletions", AUDIT_URL_CONFIG.defaults);
    expect(applied).toEqual({ ...base, range: "30d", tenant_id: filters.tenant_id, verb: "deleted" });
    expect(activeAuditView(applied, AUDIT_URL_CONFIG.defaults)).toBe("deletions");
    expect(activeAuditView(base, AUDIT_URL_CONFIG.defaults)).toBe("all");
  });

  it("liest Tokens, Personen und Mandanten nur als Auswahl, nie als Namen", () => {
    expect(parseAuditTokens("quelle:26CA aktion:protocol vorgang:gelöscht rest", aliases, verbs)).toEqual({
      patch: { source: "26ca", action: "protocol", verb: "deleted" }, rest: "rest", pick: null, invalid: [],
    });
    const person = parseAuditTokens("person:timo", aliases, verbs);
    expect(person.pick).toBe("person");
    expect(person.patch).toEqual({});
    expect(parseAuditTokens("mandant:Jungwacht", aliases, verbs).pick).toBe("tenant");
    const named = parseAuditTokens("person:Vorname Nachname", aliases, verbs);
    expect(named).toEqual({ patch: {}, rest: "", pick: "person", invalid: [] });
    expect(parseAuditTokens("quelle:xy vorgang:gemalt farbe:rot", aliases, verbs).invalid).toEqual(["quelle:xy", "vorgang:gemalt", "farbe:rot"]);
    expect(parseAuditTokens("vorgang:viewed", aliases, verbs).patch).toEqual({ verb: "viewed" });
  });

  it("ein offener Token geht nicht als Aktions-Präfix ans Backend", () => {
    expect(auditApiQuery({ ...base, action: "quelle:26" }).has("action")).toBe(false);
    expect(auditApiQuery({ ...base, verb: "deleted" }).get("verb")).toBe("deleted");
  });
});
