import { expect, it } from "vitest";

import { swipeDirection } from "./photo-viewer";

it("maps horizontal swipes to next/previous and ignores taps and vertical scrolling", () => {
  expect(swipeDirection(300, 200, 200, 210)).toBe("next");
  expect(swipeDirection(100, 200, 220, 190)).toBe("prev");
  expect(swipeDirection(100, 200, 120, 200)).toBeNull();
  expect(swipeDirection(100, 100, 160, 300)).toBeNull();
});
