import { describe, expect, it } from "vitest";

import { isHeicName, isLiveClipName, pairLiveClips } from "./live-photo";

describe("pairLiveClips", () => {
  it("ordnet einen Clip dem Bild mit gleichem Namen zu, unabhängig von Gross-/Kleinschreibung", () => {
    expect([...pairLiveClips(["IMG_1.HEIC", "img_1.mov", "IMG_2.JPG", "IMG_3.HEIC", "IMG_3.MP4"])]).toEqual([
      [0, 1],
      [3, 4],
    ]);
  });

  it("verwendet einen Clip nur einmal und lässt Clips ohne Bild aus", () => {
    expect([...pairLiveClips(["a.heic", "a.jpg", "a.mov", "lonely.mov"])]).toEqual([[0, 2]]);
  });

  it("ordnet nichts zu, wenn es keine Clips gibt", () => {
    expect(pairLiveClips(["a.heic", "b.jpg"]).size).toBe(0);
  });
});

describe("Dateinamen", () => {
  it("erkennt HEIC und Clips an der Endung", () => {
    expect(isHeicName("IMG_1.HEIC")).toBe(true);
    expect(isHeicName("IMG_1.jpg")).toBe(false);
    expect(isLiveClipName("IMG_1.MOV")).toBe(true);
    expect(isLiveClipName("IMG_1.heic")).toBe(false);
  });
});
