import { expect, it } from "vitest";
import { todoDuePresetDate } from "./todo-due";

it("uses Sunday as the week end, including today on Sundays", () => {
  expect(todoDuePresetDate("endOfWeek", new Date(2026, 9, 5))).toBe("2026-10-11");
  expect(todoDuePresetDate("endOfWeek", new Date(2026, 9, 11))).toBe("2026-10-11");
});
it("handles leap years and year boundaries", () => {
  expect(todoDuePresetDate("endOfMonth", new Date(2028, 1, 3))).toBe("2028-02-29");
  expect(todoDuePresetDate("inTwoWeeks", new Date(2026, 11, 25))).toBe("2027-01-08");
});
it("adds calendar days across daylight saving time changes", () => {
  expect(todoDuePresetDate("inTwoWeeks", new Date(2026, 9, 18))).toBe("2026-11-01");
});
