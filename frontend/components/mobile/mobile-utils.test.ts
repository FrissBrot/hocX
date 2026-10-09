import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { daysBetween, initials, isTodoDone, isTodoOverdue, relativeDay, todayIso } from "@/components/mobile/mobile-utils";
import { isMobileUserAgent } from "@/lib/utils/viewport";

const t = (key: string, values?: Record<string, string | number | Date>) => (values ? `${key}:${values.count}` : key);

describe("mobile-utils", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 6, 31, 12, 0, 0));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("liefert das heutige Datum in Geraetezeit", () => {
    expect(todayIso()).toBe("2026-07-31");
  });

  it("zaehlt Kalendertage unabhaengig von der Uhrzeit", () => {
    expect(daysBetween("2026-07-31", "2026-08-12")).toBe(12);
    expect(daysBetween("2026-07-31", "2026-07-30")).toBe(-1);
  });

  it("formuliert relative Tage ueber die uebergebenen Texte", () => {
    expect(relativeDay("2026-07-31", t)).toBe("relative.today");
    expect(relativeDay("2026-08-01", t)).toBe("relative.tomorrow");
    expect(relativeDay("2026-07-30", t)).toBe("relative.yesterday");
    expect(relativeDay("2026-08-12", t)).toBe("relative.inDays:12");
    expect(relativeDay("2026-07-27", t)).toBe("relative.daysAgo:4");
  });

  it("wertet erledigte und abgebrochene Todos als erledigt", () => {
    expect(isTodoDone({ todo_status_code: "done" })).toBe(true);
    expect(isTodoDone({ todo_status_code: "cancelled" })).toBe(true);
    expect(isTodoDone({ todo_status_code: "in_progress" })).toBe(false);
  });

  it("markiert nur offene Todos mit vergangenem Termin als ueberfaellig", () => {
    expect(isTodoOverdue({ todo_status_code: "open", resolved_due_date: "2026-07-30" })).toBe(true);
    expect(isTodoOverdue({ todo_status_code: "open", resolved_due_date: "2026-07-31" })).toBe(false);
    expect(isTodoOverdue({ todo_status_code: "done", resolved_due_date: "2026-07-01" })).toBe(false);
    expect(isTodoOverdue({ todo_status_code: "open", resolved_due_date: null })).toBe(false);
  });

  it("bildet Initialen aus maximal zwei Namensteilen", () => {
    expect(initials("Anna Berger")).toBe("AB");
    expect(initials("Jean-Luc  de la Croix")).toBe("JD");
    expect(initials(null)).toBe("");
  });
});

describe("isMobileUserAgent", () => {
  it("erkennt Smartphones, nicht aber Desktop-Browser", () => {
    expect(isMobileUserAgent("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile/15E148")).toBe(true);
    expect(isMobileUserAgent("Mozilla/5.0 (Linux; Android 15; Pixel 9) Mobile Safari/537.36")).toBe(true);
    expect(isMobileUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0")).toBe(false);
    expect(isMobileUserAgent(null)).toBe(false);
  });
});
