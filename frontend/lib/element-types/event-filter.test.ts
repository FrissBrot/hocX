import { describe, expect, it } from "vitest";
import { applyEventFilter, columnFilterTags, eventFilterTagText, eventMatchesFilter, normalizeEventFilter } from "./event-filter";

const event = (id: string, title: string, event_date: string, extra: Partial<{ tag: string; event_end_date: string; description: string; cycle_assignments: { cycle_config_id: string; cycle_year: number }[] }> = {}) => ({
  id,
  title,
  event_date,
  tag: extra.tag ?? "",
  event_end_date: extra.event_end_date ?? null,
  description: extra.description ?? "",
  cycle_assignments: extra.cycle_assignments ?? [],
});

describe("event-filter (gleiche Fälle wie backend/tests/test_element_config.py)", () => {
  it("Tags: «enthält», Gross/klein egal", () => {
    const filter = normalizeEventFilter({ tags: ["sitzung"] });
    expect(eventMatchesFilter(event("1", "A", "2026-01-01", { tag: "Vorstandssitzung" }), filter)).toBe(true);
    expect(eventMatchesFilter(event("2", "B", "2026-01-01", { tag: "lager" }), filter)).toBe(false);
  });

  it("Zeitraum relativ zum Protokolldatum", () => {
    const events = [
      event("1", "Vorher", "2026-05-01"),
      event("2", "Lager", "2026-05-30", { event_end_date: "2026-06-02" }),
      event("3", "Später", "2026-07-01"),
    ];
    const titles = (range: Record<string, unknown>) =>
      applyEventFilter(events, normalizeEventFilter({ range }), { protocolDate: "2026-06-01" }).map((e) => e.title);
    expect(titles({ mode: "all" })).toEqual(["Vorher", "Lager", "Später"]);
    expect(titles({ mode: "future" })).toEqual(["Lager", "Später"]);
    expect(titles({ mode: "past" })).toEqual(["Vorher"]);
    expect(titles({ mode: "window", start_days: -3, end_days: 3 })).toEqual(["Lager"]);
  });

  it("Spaltenfilter: eigener Tag-Filter, sonst Spaltentitel", () => {
    expect(columnFilterTags({ title: "Vorstand", event_tag_filter: "vs, präsidium" })).toEqual(["vs", "präsidium"]);
    expect(columnFilterTags({ title: "Vorstand" })).toEqual(["Vorstand"]);
    const filter = normalizeEventFilter({ use_column_filter: true });
    expect(eventMatchesFilter(event("1", "A", "2026-01-01", { tag: "vorstand" }), filter, { column: { title: "Vorstand" } })).toBe(true);
    expect(eventMatchesFilter(event("2", "B", "2026-01-01", { tag: "lager" }), filter, { column: { title: "Vorstand" } })).toBe(false);
    expect(eventFilterTagText(filter, { title: "Vorstand" })).toBe("Vorstand");
  });

  it("Titel, Beschreibung, Zyklus, Sortierung und Anzahl", () => {
    const vereinsjahr = { id: "vj", reset_month: 7, reset_day: 31 };
    const filter = normalizeEventFilter({ title: "gv", description: "wahl", sort: "desc", limit: 1, cycle: { config_id: null, offset: 0 } });
    const events = [
      event("1", "GV 2025", "2026-03-01", { description: "Wahlen", cycle_assignments: [{ cycle_config_id: "vj", cycle_year: 2025 }] }),
      event("2", "GV 2026", "2026-09-01", { description: "Wahlen", cycle_assignments: [{ cycle_config_id: "vj", cycle_year: 2026 }] }),
      event("3", "Hock", "2026-09-02", { description: "Wahlen", cycle_assignments: [{ cycle_config_id: "vj", cycle_year: 2026 }] }),
    ];
    const context = { protocolDate: "2026-10-01", resolveCycle: () => vereinsjahr };
    expect(applyEventFilter(events, filter, context).map((e) => e.title)).toEqual(["GV 2026"]);
    expect(applyEventFilter(events, { ...filter, cycle: { config_id: null, offset: -1 } }, context).map((e) => e.title)).toEqual(["GV 2025"]);
  });

  it("Vorlage ohne Zyklus filtert nicht nach Zyklus (wie das Backend)", () => {
    const filter = normalizeEventFilter({ cycle: { config_id: null, offset: 0 } });
    expect(eventMatchesFilter(event("1", "A", "2026-01-01"), filter, { protocolDate: "2026-02-01", resolveCycle: () => null })).toBe(true);
  });

  it("ergänzt fehlende Felder und verwirft ungültige Werte", () => {
    expect(normalizeEventFilter({ tags: "a, b, a", range: { mode: "bald" }, limit: -2 }, "future")).toEqual({
      tags: ["a", "b"],
      title: "",
      description: "",
      range: { mode: "future", start_days: 0, end_days: 14 },
      cycle: null,
      use_column_filter: false,
      sort: "asc",
      limit: null,
    });
  });
});
