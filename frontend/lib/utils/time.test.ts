import { describe, expect, it } from "vitest";

import { formatTimeValue, parseTimeInputValue } from "./time";

describe("parseTimeInputValue", () => {
  it.each([
    ["9", "09:00"],
    ["09", "09:00"],
    ["930", "09:30"],
    ["230", "02:30"],
    ["0930", "09:30"],
    ["1130", "11:30"],
    ["11:30", "11:30"],
    ["9.30", "09:30"],
    ["9,30", "09:30"],
    ["9h30", "09:30"],
    ["9 30", "09:30"],
    ["11:5", "11:05"],
    ["14 Uhr", "14:00"],
    ["14h", "14:00"],
    ["1130h", "11:30"],
    ["13:30:00", "13:30"],
    [" 7pm ", "19:00"],
    ["7:30 p.m.", "19:30"],
    ["12am", "00:00"],
    ["12pm", "12:00"],
    ["0", "00:00"],
    ["23:59", "23:59"],
  ])("%s → %s", (input, expected) => {
    expect(parseTimeInputValue(input)).toBe(expected);
  });

  it.each(["", "abc", "24", "24:00", "25", "1260", "9:75", "13pm", "12345", "1:2:3:4"])("%s ist ungültig", (input) => {
    expect(parseTimeInputValue(input)).toBeNull();
  });
});

describe("formatTimeValue", () => {
  it("kürzt API-Zeiten auf HH:MM", () => {
    expect(formatTimeValue("08:15:00")).toBe("08:15");
    expect(formatTimeValue(null)).toBe("");
  });
});
