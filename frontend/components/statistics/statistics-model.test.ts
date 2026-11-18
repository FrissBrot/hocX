import { describe, expect, it } from "vitest";

import {
  attendanceBars,
  attendanceRate,
  financeView,
  fineTypeRows,
  finesByPerson,
  groupRows,
  memberRows,
  statisticsPath,
  sumAttendance,
  trendOf,
  yearMonths,
} from "./statistics-model";

const month = (m: string, present: number, late: number, excused: number, absent: number) => ({ month: m, present, late, excused, absent, total: present + late + excused + absent });

describe("statistics-model", () => {
  it("zählt Verspätete als anwesend", () => {
    expect(attendanceRate(sumAttendance([month("2026-01", 6, 2, 1, 1)]))).toBeCloseTo(0.8);
    expect(attendanceRate(sumAttendance([]))).toBeNull();
  });

  it("zeigt im laufenden Jahr die Monate bis heute", () => {
    expect(yearMonths(2026, "2026-03-05")).toEqual(["2026-01", "2026-02", "2026-03"]);
    expect(yearMonths(2025, "2026-03-05")).toHaveLength(12);
  });

  it("legt die Vorjahresquote auf denselben Monat", () => {
    const bars = attendanceBars([month("2026-02", 3, 0, 0, 1)], [month("2025-02", 1, 0, 0, 1)], ["2026-01", "2026-02"]);
    expect(bars[0]).toMatchObject({ rate: null, previousRate: null, present: 0 });
    expect(bars[1]).toMatchObject({ rate: 0.75, previousRate: 0.5, present: 0.75, absent: 0.25 });
  });

  it("sortiert Mitglieder nach Quote", () => {
    const rows = memberRows([{ name: "A", ...month("", 1, 0, 0, 1) }, { name: "B", ...month("", 2, 0, 0, 0) }], "low");
    expect(rows.map((row) => row.name)).toEqual(["A", "B"]);
  });

  it("führt Bussen einer Person über Währungen zusammen", () => {
    const rows = finesByPerson([
      { name: "Otto", participant_key: "id:1", count: 2, amount: 60, currency: "CHF", absent_count: 1, late_count: 1 },
      { name: "Otto", participant_key: "id:1", count: 1, amount: 7, currency: "EUR", absent_count: 1, late_count: 0 },
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ absent: 2, late: 1, count: 3 });
    expect(rows[0].totals.map((total) => total.currency)).toEqual(["CHF", "EUR"]);
  });

  it("zeigt in der eigenen Sicht die Bussen nach Art aus der eigenen Zeile", () => {
    const rows = fineTypeRows({
      per_person_scope: "own",
      fines_by_type: [{ fine_type: "absent", label: "", count: 9, amount: 450, currency: "CHF" }],
      fines_by_participant: [{ name: "Lea", count: 1, amount: 10, currency: "CHF", absent_count: 0, late_count: 1, absent_amount: 0, late_amount: 10 }],
    });
    expect(rows).toEqual([{ fineType: "late", count: 1, totals: [{ currency: "CHF", count: 1, amount: 10 }] }]);
  });

  it("rechnet Finanzen je Konto und Monat und das Vorjahr", () => {
    const view = financeView(
      {
        finance_by_month: [
          { month: "2026-01", account_id: "a", account_name: "Kasse", currency: "CHF", income: 300, expenses: 100, net: 200 },
          { month: "2026-02", account_id: "b", account_name: "Bank", currency: "CHF", income: 0, expenses: 450, net: -450 },
        ],
        comparison: { finance_by_account: [{ account_id: "a", account_name: "Kasse", income: 100, expenses: 50 }] } as never,
      },
      "all",
      ["2026-01", "2026-02"]
    );
    expect(view).toMatchObject({ income: 300, expenses: 550, net: -250, currency: "CHF", scale: 450 });
    expect(view.previous).toEqual({ income: 100, expenses: 50, net: 50 });
    expect(financeView({ finance_by_month: [], comparison: null }, "a", ["2026-01"]).net).toBe(0);
  });

  it("gewichtet Ø Teilnehmende über Zyklen", () => {
    const rows = groupRows([
      { group_name: "Jugend", cycle_config_id: "c", cycle_year: 2025, session_count: 2, session_count_with_participants: 1, avg_participants: 10 },
      { group_name: "Jugend", cycle_config_id: "c", cycle_year: 2026, session_count: 3, session_count_with_participants: 3, avg_participants: 6 },
    ]);
    expect(rows).toEqual([{ name: "Jugend", sessions: 5, withParticipants: 4, avgParticipants: 7 }]);
  });

  it("bewertet Veränderungen", () => {
    expect(trendOf(0.9, 0.8)).toEqual({ trend: "up", good: true });
    expect(trendOf(100, 50, false)).toEqual({ trend: "up", good: false });
    expect(trendOf(1, 1).trend).toBe("flat");
  });

  it("baut den Pfad mit Jahr und Vergleich", () => {
    expect(statisticsPath(2026, true)).toBe("/api/statistics/overview?year=2026&compare=true");
  });
});
