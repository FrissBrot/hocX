import { describe, expect, it, vi } from "vitest";

import { nativeSmoothScroll, passiveSnapTarget, scrollDuration, sectionScrollTarget, wheelVars } from "./document-scroll";

describe("sectionScrollTarget", () => {
  const base = { viewport: 800, scrollHeight: 5000, first: false };

  it("zentriert kurze Punkte und setzt lange und den ersten oben an", () => {
    expect(sectionScrollTarget({ ...base, top: 1000, height: 200 })).toBe(700);
    expect(sectionScrollTarget({ ...base, top: 1000, height: 900 })).toBe(984);
    expect(sectionScrollTarget({ ...base, top: 400, height: 200, first: true })).toBe(384);
  });

  it("bleibt im Scrollbereich", () => {
    expect(sectionScrollTarget({ ...base, top: 100, height: 100 })).toBe(0);
    expect(sectionScrollTarget({ ...base, top: 4900, height: 100 })).toBe(4200);
  });
});

describe("passiveSnapTarget", () => {
  const base = { viewport: 800, scrollTop: 1000 };

  it("setzt lange Punkte nach unten mit dem Anfang oben, nach oben mit dem Ende unten an", () => {
    expect(passiveSnapTarget({ ...base, top: 1200, height: 1500, up: false })).toBe(1184);
    expect(passiveSnapTarget({ ...base, top: 1200, height: 1500, up: true })).toBe(1916);
  });

  it("verschiebt kurze Punkte nur so weit, dass sie ganz im Bild stehen", () => {
    expect(passiveSnapTarget({ ...base, top: 1200, height: 300, up: false })).toBe(1000);
    expect(passiveSnapTarget({ ...base, top: 950, height: 300, up: true })).toBe(934);
    expect(passiveSnapTarget({ ...base, top: 1600, height: 300, up: true })).toBe(1116);
  });
});

describe("wheelVars", () => {
  it("lässt den aktiven Punkt und weit entfernte Punkte flach", () => {
    expect(wheelVars(0)).toBeNull();
    expect(wheelVars(11)).toBeNull();
    expect(wheelVars(-11)).toBeNull();
    expect(wheelVars(Number.NaN)).toBeNull();
  });

  it("legt Punkte darüber und darunter auf die Walze, zunehmend bis vier Punkte Abstand", () => {
    expect(wheelVars(-1)).toEqual({ "--wheel-dir": "-1", "--wheel-depth": "0.156" });
    expect(wheelVars(2)).toEqual({ "--wheel-dir": "1", "--wheel-depth": "0.500" });
    expect(wheelVars(4)).toEqual({ "--wheel-dir": "1", "--wheel-depth": "1.000" });
    expect(wheelVars(-10)).toEqual({ "--wheel-dir": "-1", "--wheel-depth": "1.000" });
  });
});

describe("nativeSmoothScroll", () => {
  it("meldet das Ende bei scrollend genau einmal", () => {
    const container = document.createElement("div");
    container.scrollTo = vi.fn() as unknown as HTMLElement["scrollTo"];
    const onDone = vi.fn();
    const stop = nativeSmoothScroll(container, 300, { onDone });
    expect(container.scrollTo).toHaveBeenCalledWith({ top: 300, behavior: "smooth" });
    container.dispatchEvent(new Event("scrollend"));
    stop();
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("hält beim Abbruch an und meldet das Ende auch ohne scrollend", () => {
    vi.useFakeTimers();
    try {
      const container = document.createElement("div");
      container.scrollTo = vi.fn() as unknown as HTMLElement["scrollTo"];
      const onDone = vi.fn();
      nativeSmoothScroll(container, 300, { onDone });
      vi.advanceTimersByTime(1300);
      expect(onDone).toHaveBeenCalledTimes(1);

      const other = vi.fn();
      const stop = nativeSmoothScroll(container, 500, { onDone: other });
      stop();
      expect(container.scrollTo).toHaveBeenLastCalledWith({ top: 0, behavior: "instant" });
      expect(other).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

it("skaliert die Sprungdauer mit der Distanz", () => {
  expect(scrollDuration(0)).toBe(260);
  expect(scrollDuration(-400)).toBe(360);
  expect(scrollDuration(5000)).toBe(620);
});
