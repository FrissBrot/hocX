import { describe, expect, it } from "vitest";
import {
  formatDate,
  formatDateInputValue,
  formatDateRange,
  formatDateTime,
  parseDateInputValue,
} from "./format";

describe("formatDate", () => {
  it("formats an ISO date string as dd.mm.yyyy", () => {
    expect(formatDate("2026-03-01")).toBe("01.03.2026");
  });

  it("formats an ISO datetime string using only the date part", () => {
    expect(formatDate("2026-03-01T12:34:56Z")).toBe("01.03.2026");
  });

  it("returns an empty string for null/undefined/empty input", () => {
    expect(formatDate(null)).toBe("");
    expect(formatDate(undefined)).toBe("");
    expect(formatDate("")).toBe("");
  });

  it("falls back to the raw input for a string that is not a valid date at all", () => {
    expect(formatDate("not a date")).toBe("not a date");
  });
});

describe("formatDateRange", () => {
  it("returns a single formatted date when start and end are the same day", () => {
    expect(formatDateRange("2026-03-01", "2026-03-01")).toBe("01.03.2026");
  });

  it("joins distinct start/end dates with a dash", () => {
    expect(formatDateRange("2026-03-01", "2026-03-05")).toBe("01.03.2026 - 05.03.2026");
  });

  it("returns just the start date when there is no end date", () => {
    expect(formatDateRange("2026-03-01", null)).toBe("01.03.2026");
    expect(formatDateRange("2026-03-01")).toBe("01.03.2026");
  });

  it("returns an empty string when there is no start date", () => {
    expect(formatDateRange(null, "2026-03-05")).toBe("");
  });
});

describe("parseDateInputValue", () => {
  it("accepts a valid ISO date", () => {
    expect(parseDateInputValue("2026-03-01")).toBe("2026-03-01");
  });

  it("normalizes a dd.mm.yyyy display date to ISO", () => {
    expect(parseDateInputValue("1.3.2026")).toBe("2026-03-01");
    expect(parseDateInputValue("01.03.2026")).toBe("2026-03-01");
  });

  it("returns an empty string for empty/blank input", () => {
    expect(parseDateInputValue("")).toBe("");
    expect(parseDateInputValue("   ")).toBe("");
    expect(parseDateInputValue(null)).toBe("");
  });

  it("returns null for a syntactically-plausible but calendar-invalid date", () => {
    expect(parseDateInputValue("2026-02-30")).toBeNull();
    expect(parseDateInputValue("31.04.2026")).toBeNull();
  });

  it("returns null for garbage input", () => {
    expect(parseDateInputValue("hello world")).toBeNull();
  });
});

describe("formatDateInputValue", () => {
  it("round-trips a display-format date through parsing and formatting", () => {
    expect(formatDateInputValue("2026-03-01")).toBe("01.03.2026");
  });

  it("returns an empty string for an unparseable date", () => {
    expect(formatDateInputValue("not-a-date")).toBe("");
  });
});

describe("formatDateTime", () => {
  it("formats an ISO datetime with date and 24h time", () => {
    // Europe/Zurich is UTC+1 in March (before DST switch in late March).
    expect(formatDateTime("2026-03-01T09:30:00Z")).toBe("01.03.2026, 10:30");
  });

  it("returns an empty string for null/undefined input", () => {
    expect(formatDateTime(null)).toBe("");
    expect(formatDateTime(undefined)).toBe("");
  });

  it("falls back to formatDate for an unparseable datetime", () => {
    expect(formatDateTime("not a date")).toBe(formatDate("not a date"));
  });
});
