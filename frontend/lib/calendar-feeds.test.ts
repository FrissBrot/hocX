import { describe, expect, it } from "vitest";

import { appleSubscribeUrl, calendarFeedUrl, canSubscribeCalendar, googleSubscribeUrl } from "@/lib/calendar-feeds";

const PATH = "/api/public/calendar/abc_DEF-123.ics";

describe("calendar-feeds", () => {
  it("setzt die eigene Origin vor den relativen Feed-Pfad", () => {
    expect(calendarFeedUrl(PATH, "https://hocx.example.ch")).toBe("https://hocx.example.ch/api/public/calendar/abc_DEF-123.ics");
  });

  it("baut fuer Apple einen webcal-Link, auch von http aus", () => {
    expect(appleSubscribeUrl(PATH, "https://hocx.example.ch")).toBe("webcal://hocx.example.ch/api/public/calendar/abc_DEF-123.ics");
    expect(appleSubscribeUrl(PATH, "http://localhost:3000")).toBe("webcal://localhost:3000/api/public/calendar/abc_DEF-123.ics");
  });

  it("uebergibt Google die webcal-Adresse kodiert als cid", () => {
    const url = new URL(googleSubscribeUrl(PATH, "https://hocx.example.ch"));
    expect(url.origin).toBe("https://calendar.google.com");
    expect(url.searchParams.get("cid")).toBe("webcal://hocx.example.ch/api/public/calendar/abc_DEF-123.ics");
  });

  it("bietet Termine nur Schreibenden an, Todos allen Rollen", () => {
    expect(canSubscribeCalendar("writer", "events")).toBe(true);
    expect(canSubscribeCalendar("reader", "events")).toBe(false);
    expect(canSubscribeCalendar("kassier", "events")).toBe(false);
    expect(canSubscribeCalendar("reader", "todos")).toBe(true);
    expect(canSubscribeCalendar(null, "todos")).toBe(false);
  });
});
