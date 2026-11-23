import { afterEach, describe, expect, it, vi } from "vitest";

import { createSectionSpy, SPY_ROOT_MARGIN } from "./section-spy";

type Callback = (entries: Array<{ target: Element; isIntersecting: boolean }>) => void;

describe("createSectionSpy", () => {
  let callback: Callback | null = null;
  let options: IntersectionObserverInit | undefined;
  const observed: Element[] = [];

  afterEach(() => {
    vi.unstubAllGlobals();
    observed.length = 0;
  });

  function setup() {
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(cb: Callback, init?: IntersectionObserverInit) {
          callback = cb;
          options = init;
        }
        observe(element: Element) { observed.push(element); }
        disconnect() { observed.length = 0; }
      }
    );
    const root = document.createElement("div");
    let scrollTop = 500;
    Object.defineProperty(root, "scrollTop", { get: () => scrollTop, set: (value: number) => { scrollTop = value; } });
    const sections = ["a", "b", "c"].map((id) => {
      const section = document.createElement("section");
      section.dataset.sec = id;
      return section;
    });
    const onActive = vi.fn();
    const spy = createSectionSpy(root, (section) => (section as HTMLElement).dataset.sec ?? null, onActive)!;
    spy.observe(sections);
    return { root, sections, onActive, spy };
  }

  it("beobachtet alle Punkte mit dem oberen Drittel als Bereich", () => {
    const { sections } = setup();
    expect(observed).toEqual(sections);
    expect(options?.rootMargin).toBe(SPY_ROOT_MARGIN);
  });

  it("meldet den obersten sichtbaren Punkt in Dokumentreihenfolge und nur bei Wechsel", () => {
    const { sections, onActive } = setup();
    callback?.([{ target: sections[2], isIntersecting: true }, { target: sections[1], isIntersecting: true }]);
    expect(onActive).toHaveBeenLastCalledWith("b");
    callback?.([{ target: sections[2], isIntersecting: true }]);
    expect(onActive).toHaveBeenCalledTimes(1);
    callback?.([{ target: sections[1], isIntersecting: false }]);
    expect(onActive).toHaveBeenLastCalledWith("c");
  });

  it("schweigt während eines Sprungs und meldet danach den Stand", () => {
    const { sections, onActive, spy } = setup();
    spy.setPaused(true);
    callback?.([{ target: sections[1], isIntersecting: true }]);
    expect(onActive).not.toHaveBeenCalled();
    spy.setCurrent("b");
    spy.setPaused(false);
    expect(onActive).not.toHaveBeenCalled();
  });

  it("wählt am Anfang des Dokuments den ersten Punkt", () => {
    const { root, sections, onActive } = setup();
    root.scrollTop = 0;
    callback?.([{ target: sections[1], isIntersecting: true }]);
    expect(onActive).toHaveBeenLastCalledWith("a");
  });
});
