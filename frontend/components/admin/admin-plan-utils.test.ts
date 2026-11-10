import { describe, expect, it } from "vitest";

import { clampDiscountPercent, discountedRp, discountPercentForPrice } from "./admin-plan-utils";

describe("Rabatt über Prozent oder Preis", () => {
  it("rechnet einen Wunschpreis rappengenau in Prozent um", () => {
    for (const [subtotal, target] of [
      [24990, 19900],
      [2000, 1500],
      [999_900, 777_705],
      [12345, 1],
      [12345, 12345],
    ]) {
      const percent = discountPercentForPrice(subtotal, target);
      expect(discountedRp(subtotal, percent)).toBe(target);
    }
    expect(discountPercentForPrice(24990, 19900)).toBe(20.3681);
  });

  it("begrenzt auf 0–100 % mit 4 Nachkommastellen", () => {
    expect(discountPercentForPrice(2000, 3000)).toBe(0);
    expect(discountPercentForPrice(2000, -5)).toBe(100);
    expect(discountPercentForPrice(0, 100)).toBe(0);
    expect(clampDiscountPercent(12.345678)).toBe(12.3457);
    expect(clampDiscountPercent(Number.NaN)).toBe(0);
  });
});
