import { describe, expect, it } from "vitest";

import { DERIVED_COLOR_KEYS, deriveBrandColors, mixColor } from "./brand-colors";

describe("brand colors", () => {
  it("mixes two colors", () => {
    expect(mixColor("#000000", "#FFFFFF", 0.5)).toBe("#808080");
    expect(mixColor("#174b7a", "#FFFFFF", 0)).toBe("#174B7A");
  });

  it("derives the remaining colors from primary and secondary", () => {
    const colors = deriveBrandColors("#174B7A", "#4F6D7A");
    expect(colors.heading).toBe("#174B7A");
    expect(colors.accent).toBe("#4F6D7A");
    expect(colors.background).toBe("#FFFFFF");
    expect(colors.table_header_background).toBe("#E8EDF2");
    expect(Object.values(colors).every((value) => /^#[0-9A-F]{6}$/.test(value))).toBe(true);
    expect(DERIVED_COLOR_KEYS).not.toContain("primary");
    expect(DERIVED_COLOR_KEYS).not.toContain("danger");
  });
});
