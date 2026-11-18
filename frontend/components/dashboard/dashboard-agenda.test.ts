import { describe, expect, it } from "vitest";

import { groupAgenda, type AgendaItem } from "./dashboard-agenda";

const item = (id: string, date: string, kind: AgendaItem["kind"] = "event"): AgendaItem => ({ id, date, title: id, sub: "", kind, href: null });

describe("groupAgenda", () => {
  // Mittwoch, 18. November 2026
  const today = "2026-11-18";

  it("gruppiert nach dieser Woche, nächster Woche und Monat", () => {
    const groups = groupAgenda(
      [item("gv", "2026-12-12"), item("wanderung", "2026-11-21"), item("sitzung", "2026-11-24", "session"), item("frist", "2026-11-22", "deadline"), item("chlaus", "2026-12-05")],
      today,
      10
    );
    expect(groups.map((group) => [group.key, group.items.map((entry) => entry.id)])).toEqual([
      ["thisWeek", ["wanderung", "frist"]],
      ["nextWeek", ["sitzung"]],
      ["month:2026-12", ["chlaus", "gv"]],
    ]);
  });

  it("lässt Vergangenes weg und begrenzt die Anzahl", () => {
    const groups = groupAgenda([item("alt", "2026-11-17"), item("a", "2026-11-18"), item("b", "2026-11-19"), item("c", "2026-11-20")], today, 2);
    expect(groups.flatMap((group) => group.items.map((entry) => entry.id))).toEqual(["a", "b"]);
  });

  it("Sonntag gehört noch zur laufenden Woche", () => {
    expect(groupAgenda([item("so", "2026-11-22"), item("mo", "2026-11-23")], today, 5).map((group) => group.key)).toEqual(["thisWeek", "nextWeek"]);
  });
});
