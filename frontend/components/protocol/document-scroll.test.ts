import { describe, expect, it, vi } from "vitest";

import { jumpToSection, nativeSmoothScroll, scrollDuration, sectionScrollTarget } from "./document-scroll";

describe("sectionScrollTarget", () => {
  const base = { viewport: 800, scrollHeight: 5000 };

  it("setzt den Kopf des Punkts oben an", () => {
    expect(sectionScrollTarget({ ...base, top: 1000 })).toBe(984);
  });

  it("bleibt im Scrollbereich", () => {
    expect(sectionScrollTarget({ ...base, top: 10 })).toBe(0);
    expect(sectionScrollTarget({ ...base, top: 4900 })).toBe(4200);
  });
});

describe("jumpToSection", () => {
  function setup(sectionTop: number) {
    const container = document.createElement("div");
    const section = document.createElement("section");
    container.appendChild(section);
    let scrollTop = 0;
    Object.defineProperties(container, {
      clientHeight: { value: 800 },
      scrollHeight: { value: 20000 },
      scrollTop: { get: () => scrollTop, set: (value: number) => { scrollTop = value; } },
    });
    let top = sectionTop;
    Object.defineProperty(section, "offsetTop", { get: () => top });
    Object.defineProperty(section, "offsetParent", { get: () => container });
    return { container, section, moveSection: (value: number) => { top = value; } };
  }

  it("springt nahe Ziele direkt an", () => {
    const { container, section } = setup(600);
    const onDone = vi.fn();
    jumpToSection(container, section, { smooth: false, onDone });
    expect(container.scrollTop).toBe(584);
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("springt weit entfernte Ziele in zwei Stufen an und misst dazwischen neu", () => {
    vi.useFakeTimers();
    const frames: FrameRequestCallback[] = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      frames.push(callback);
      return frames.length;
    });
    const { container, section, moveSection } = setup(9000);
    const onDone = vi.fn();
    jumpToSection(container, section, { smooth: false, onDone });
    // Stufe 1: sofort in die Nähe (geschätzte Lage)
    expect(container.scrollTop).toBe(8984);
    expect(onDone).not.toHaveBeenCalled();
    // Nach dem Rendern der Nachbarn liegt der Punkt woanders
    moveSection(9400);
    frames.shift()?.(0);
    frames.shift()?.(0);
    expect(container.scrollTop).toBe(9384);
    expect(onDone).toHaveBeenCalledTimes(1);
    vi.restoreAllMocks();
    vi.useRealTimers();
  });
});

function scrollBox(scrollTop: number, scrollHeight = 2000, clientHeight = 800) {
  const container = document.createElement("div");
  Object.defineProperty(container, "scrollHeight", { value: scrollHeight });
  Object.defineProperty(container, "clientHeight", { value: clientHeight });
  container.scrollTop = scrollTop;
  container.scrollTo = vi.fn() as unknown as HTMLElement["scrollTo"];
  return container;
}

describe("nativeSmoothScroll", () => {
  it("meldet das Ende bei scrollend genau einmal", () => {
    const container = scrollBox(300);
    const onDone = vi.fn();
    const stop = nativeSmoothScroll(container, 300, { onDone });
    expect(container.scrollTo).toHaveBeenCalledWith({ top: 300, behavior: "smooth" });
    container.dispatchEvent(new Event("scrollend"));
    stop();
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("ignoriert ein scrollend, das noch nicht am Ziel ist (verspätetes Ende eines Sprungs davor)", () => {
    const container = scrollBox(126);
    const onDone = vi.fn();
    nativeSmoothScroll(container, 650, { onDone });
    container.dispatchEvent(new Event("scrollend"));
    expect(onDone).not.toHaveBeenCalled();
    container.scrollTop = 650;
    container.dispatchEvent(new Event("scrollend"));
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("gilt am Rand des Scrollbereichs als am Ziel", () => {
    const container = scrollBox(1200, 2000, 800);
    const onDone = vi.fn();
    nativeSmoothScroll(container, 5000, { onDone });
    container.dispatchEvent(new Event("scrollend"));
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
