import { describe, expect, it } from "vitest";
import { matchesSmartQuery, smartDateCandidates, smartDateSuggestions, type SmartDateCandidate } from "./smart-dates";

// Deutsche Beschriftungen wie in messages/de/todos.json (smartDate)
const WEEKDAYS = ["", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
function describe_(candidate: SmartDateCandidate) {
  const weekday = WEEKDAYS[candidate.weekday ?? 0];
  const labels: Record<string, string> = {
    today: "Heute", tomorrow: "Morgen", dayAfterTomorrow: "Übermorgen",
    weekdayThisWeek: `${weekday} diese Woche`, weekdayNextWeek: `${weekday} nächste Woche`, weekdayNext: weekday,
    endOfWeek: "Ende Woche", startOfNextWeek: "Anfang nächste Woche", endOfNextWeek: "Ende nächste Woche",
    inTwoWeeks: "In 2 Wochen", endOfMonth: "Ende Monat", startOfNextMonth: "Anfang nächster Monat",
    endOfNextMonth: "Ende nächster Monat", endOfYear: "Ende Jahr",
    inDays: `In ${candidate.count} Tagen`, inWeeks: `In ${candidate.count} Wochen`, inMonths: `In ${candidate.count} Monaten`,
    exactDate: candidate.date,
  };
  return { label: labels[candidate.kind], keywords: candidate.kind === "endOfWeek" ? "Wochenende Sonntag" : "" };
}
// Mittwoch, 11.11.2026
const NOW = new Date(2026, 10, 11, 15, 30);
const suggest = (query: string, limit?: number) => smartDateSuggestions(query, describe_, { now: NOW, limit }).map((item) => `${item.label}=${item.date}`);

describe("smartDateSuggestions", () => {
  it("schlägt ohne Eingabe nichts vor", () => {
    expect(suggest("")).toEqual([]);
    expect(suggest("   ")).toEqual([]);
  });

  it("findet morgen und übermorgen über den Wortanfang, auch ohne Umlaut", () => {
    expect(suggest("mor")).toEqual(["Morgen=2026-11-12"]);
    expect(suggest("über")).toEqual(["Übermorgen=2026-11-13"]);
    expect(suggest("uber")).toEqual(["Übermorgen=2026-11-13"]);
  });

  it("bietet Wochentage dieser und nächster Woche an, ohne doppelte Daten", () => {
    expect(suggest("fr")).toEqual(["Freitag diese Woche=2026-11-13", "Freitag nächste Woche=2026-11-20"]);
    expect(suggest("freitag nä")).toEqual(["Freitag nächste Woche=2026-11-20"]);
    // Montag dieser Woche ist vorbei: nur der nächste
    expect(suggest("montag")).toEqual(["Montag nächste Woche=2026-11-16"]);
  });

  it("kennt Wochen-, Monats- und Jahresende", () => {
    expect(suggest("ende")).toEqual([
      "Ende Woche=2026-11-15", "Ende nächste Woche=2026-11-22", "Ende Monat=2026-11-30",
      "Ende nächster Monat=2026-12-31", "Ende Jahr=2026-12-31",
    ].filter((entry, index, all) => all.findIndex((other) => other.split("=")[1] === entry.split("=")[1]) === index));
    expect(suggest("wochenende")).toEqual(["Ende Woche=2026-11-15"]);
  });

  it("rechnet Zahlen in Tage, Wochen und Monate um", () => {
    expect(suggest("in 3")).toEqual(["In 3 Tagen=2026-11-14", "In 3 Wochen=2026-12-02", "In 3 Monaten=2027-02-11"]);
    expect(suggest("10 wo")).toEqual(["In 10 Wochen=2027-01-20"]);
  });

  it("erkennt ein getipptes Datum, ohne Jahr das nächste Vorkommen", () => {
    expect(suggest("24.12")).toEqual(["2026-12-24=2026-12-24"]);
    expect(suggest("1.3.")).toEqual(["2027-03-01=2027-03-01"]);
    expect(suggest("31.2")).toEqual([]);
  });

  it("begrenzt die Anzahl", () => {
    expect(suggest("nä", 3)).toHaveLength(3);
  });
});

describe("smartDateCandidates", () => {
  it("Monatsende ohne Überlauf und über den Jahreswechsel", () => {
    const candidates = smartDateCandidates("1", new Date(2027, 0, 31));
    expect(candidates.find((item) => item.kind === "inMonths")?.date).toBe("2027-02-28");
    expect(candidates.find((item) => item.kind === "endOfNextMonth")?.date).toBe("2027-02-28");
  });

  it("Sonntag: diese Woche nur noch Sonntag, Ende Woche ist heute", () => {
    const candidates = smartDateCandidates("", new Date(2026, 10, 15));
    expect(candidates.filter((item) => item.kind === "weekdayThisWeek").map((item) => item.weekday)).toEqual([7]);
    expect(candidates.find((item) => item.kind === "endOfWeek")?.date).toBe("2026-11-15");
  });
});

it("matchesSmartQuery verlangt jeden getippten Wortanfang", () => {
  expect(matchesSmartQuery("Freitag diese Woche", "fr di")).toBe(true);
  expect(matchesSmartQuery("Freitag diese Woche", "fr x")).toBe(false);
});
