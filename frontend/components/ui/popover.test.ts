import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { computePopoverPosition } from "./popover";

// computePopoverPosition is a pure function of (rect, align, gap, options) plus the current
// window.innerWidth/innerHeight - no DOM rendering needed, just controlling those two globals
// per test (jsdom provides `DOMRect` itself).
function setViewport(width: number, height: number) {
  Object.defineProperty(window, "innerWidth", { value: width, configurable: true });
  Object.defineProperty(window, "innerHeight", { value: height, configurable: true });
}

function rect(overrides: Partial<DOMRect>): DOMRect {
  return {
    x: 0,
    y: 0,
    width: 100,
    height: 30,
    top: 0,
    left: 0,
    right: 100,
    bottom: 30,
    toJSON() {
      return this;
    },
    ...overrides,
  } as DOMRect;
}

describe("computePopoverPosition", () => {
  const originalInnerWidth = window.innerWidth;
  const originalInnerHeight = window.innerHeight;

  beforeEach(() => {
    setViewport(1200, 800);
  });

  afterEach(() => {
    setViewport(originalInnerWidth, originalInnerHeight);
  });

  it("positions below the anchor when there is enough room below", () => {
    const anchor = rect({ top: 100, bottom: 130, left: 50, right: 150, width: 100 });
    const style = computePopoverPosition(anchor, "start", 6);

    expect(style.position).toBe("fixed");
    expect(style.top).toBe(136); // bottom (130) + gap (6)
    expect(style.bottom).toBeUndefined();
    expect(style.left).toBe(50);
    expect(style.minWidth).toBe(100);
  });

  it("flips above the anchor when there is not enough room below but there is above", () => {
    // Anchor near the bottom of a short viewport - little space below, plenty above.
    setViewport(1200, 400);
    const anchor = rect({ top: 350, bottom: 380, left: 50, right: 150, width: 100 });
    const style = computePopoverPosition(anchor, "start", 6, { estimatedHeight: 320 });

    // spaceBelow = 400 - 380 - 8 = 12 (< estimatedHeight 320)
    // spaceAbove = 350 - 8 = 342 (> spaceBelow 12) -> flips above
    expect(style.bottom).toBe(400 - 350 + 6); // innerHeight - anchor.top + gap
    expect(style.top).toBeUndefined();
  });

  it("aligns to the right edge of the anchor when align is 'end'", () => {
    const anchor = rect({ top: 100, bottom: 130, left: 50, right: 150, width: 100 });
    const style = computePopoverPosition(anchor, "end", 6);

    expect(style.right).toBe(1200 - 150); // innerWidth - anchor.right
    expect(style.left).toBeUndefined();
  });

  it("respects a minWidth floor wider than the anchor itself", () => {
    const anchor = rect({ top: 100, bottom: 130, left: 50, right: 150, width: 80 });
    const style = computePopoverPosition(anchor, "start", 6, { minWidth: 220 });

    expect(style.minWidth).toBe(220);
  });

  it("does not apply the minWidth floor when the anchor is already wider", () => {
    const anchor = rect({ top: 100, bottom: 130, left: 50, right: 150, width: 300 });
    const style = computePopoverPosition(anchor, "start", 6, { minWidth: 220 });

    expect(style.minWidth).toBe(300);
  });

  it("caps maxHeight to the available space below when positioned below", () => {
    setViewport(1200, 500);
    const anchor = rect({ top: 100, bottom: 130, left: 50, right: 150, width: 100 });
    const style = computePopoverPosition(anchor, "start", 6);

    // spaceBelow = 500 - 130 - 8 = 362, well above the default estimatedHeight (320)
    // so it stays below and maxHeight is exactly spaceBelow.
    expect(style.top).toBe(136);
    expect(style.maxHeight).toBe(362);
  });
});
