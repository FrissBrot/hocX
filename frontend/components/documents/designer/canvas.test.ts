import { describe, expect, it } from "vitest";

import { dropId, parseDropId } from "./canvas";

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
