import { describe, expect, it } from "vitest";
import { participantEligibleOn, swissDateToday } from "./participant-membership";

describe("participantEligibleOn", () => {
  it("begrenzt die Auswahl durch Ein- und Austritt einschließlich beider Stichtage", () => {
    const person = { joined_at: "2026-08-15", left_at: "2026-08-20" };
    expect(participantEligibleOn(person, "2026-08-14")).toBe(false);
    expect(participantEligibleOn(person, "2026-08-15")).toBe(true);
    expect(participantEligibleOn(person, "2026-08-20")).toBe(true);
    expect(participantEligibleOn(person, "2026-08-21")).toBe(false);
  });
  it("lässt Teilnehmer ohne Datum weiterhin zu", () => {
    expect(participantEligibleOn({}, "2026-10-04")).toBe(true);
  });
});

describe("swissDateToday", () => {
  it("liefert den Schweizer Kalendertag, nicht den UTC-Tag", () => {
    // 23.11.2026 00:30 in Zürich = 22.11.2026 23:30 UTC
    const justAfterMidnight = new Date("2026-11-22T23:30:00Z");
    expect(swissDateToday(justAfterMidnight)).toBe("2026-11-23");
    // Sommerzeit: 01.07.2026 01:30 in Zürich = 30.06.2026 23:30 UTC
    expect(swissDateToday(new Date("2026-06-30T23:30:00Z"))).toBe("2026-07-01");
    // Wer am 22.11. ausgetreten ist, ist ab 00:00 des 23.11. nicht mehr Mitglied (wie has_left im Backend)
    expect(participantEligibleOn({ left_at: "2026-11-22" }, swissDateToday(justAfterMidnight))).toBe(false);
  });
});
