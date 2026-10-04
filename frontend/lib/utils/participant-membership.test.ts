import { describe, expect, it } from "vitest";
import { participantEligibleOn } from "./participant-membership";

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
