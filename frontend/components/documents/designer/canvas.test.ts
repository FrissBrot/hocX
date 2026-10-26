import { describe, expect, it } from "vitest";

import { dropId, headingNumbers, parseDropId, spacingBetween } from "./canvas";

describe("canvas drop targets", () => {
  it("round-trips drop targets of every area including page masters", () => {
    const targets = [
      { area: "body" as const, parentId: null, index: 0 },
      { area: "body" as const, parentId: "sec", index: 3 },
      { area: "master:default:header" as const, parentId: null, index: 1 },
      { area: "title_page" as const, parentId: "layer", index: 2 },
    ];
    for (const target of targets) expect(parseDropId(dropId(target))).toEqual(target);
  });

  it("ignores foreign draggable ids", () => {
    expect(parseDropId("node|abc")).toBeNull();
    expect(parseDropId("lib|text")).toBeNull();
  });
});

describe("canvas spacing like Typst", () => {
  const par = { kind: "par" as const, above: 10, below: 10, before: null, after: null };
  const block = (above: number, below: number) => ({ kind: "block" as const, above, below, before: null, after: null });

  it("uses paragraph spacing between paragraphs and block spacing next to blocks", () => {
    expect(spacingBetween(par, par, null, 10)).toBe(10);
    expect(spacingBetween(par, block(0, 4), null, 10)).toBe(0);
    expect(spacingBetween(block(0, 4), par, null, 10)).toBe(4);
    expect(spacingBetween(block(0, 4), block(2, 0), null, 10)).toBe(4);
  });

  it("lets weak spacing (stack gap, outer margins) replace the element spacing", () => {
    expect(spacingBetween(par, par, 3, 10)).toBe(3);
    expect(spacingBetween({ ...block(0, 8), after: 2 }, { ...par, before: 5 }, 1, 10)).toBe(5);
  });

  it("drops spacing at the start of a container", () => {
    expect(spacingBetween(null, { ...par, before: 6 }, 3, 10)).toBe(0);
  });
});

describe("heading numbers", () => {
  it("counts like heading(numbering: \"1.1\") and resets deeper levels", () => {
    expect(headingNumbers([{ level: 1 }, { level: 2 }, { level: 2 }, { level: 1 }, { level: 3 }])).toEqual(["1", "1.1", "1.2", "2", "2.0.1"]);
  });
});
