import { afterEach, describe, expect, it, vi } from "vitest";

import { ACCORDION_RAMP, SKIPPED_CLASS, accordionOpenness, createAccordionEngine, type AccordionMetrics } from "./accordion-scroll";

const options = { center: 400, gap: 16, ramp: 200 };
const points = (count: number, body = 600): AccordionMetrics[] => Array.from({ length: count }, () => ({ collapsed: 80, body }));

/** Lage aller Punkte (Oberkante) für einen Bezug - wie sie der Browser nach dem Umbau zeigt. */
function layout(sections: AccordionMetrics[], open: number[], anchor: number, anchorTop: number): number[] {
  const tops = sections.map(() => 0);
  tops[anchor] = anchorTop;
  for (let index = anchor + 1; index < sections.length; index += 1) {
    const previous = sections[index - 1];
    tops[index] = tops[index - 1] + previous.collapsed + open[index - 1] * previous.body + options.gap;
  }
  for (let index = anchor - 1; index >= 0; index -= 1) {
    tops[index] = tops[index + 1] - options.gap - sections[index].collapsed - open[index] * sections[index].body;
  }
  return tops;
}

describe("accordionOpenness", () => {
  it("öffnet den Bezugspunkt ganz und lässt entfernte Punkte zu", () => {
    const open = accordionOpenness(points(5), 2, -100, options);
    expect(open[2]).toBe(1);
    expect(open[0]).toBe(0);
    expect(open[4]).toBe(0);
  });

  it("öffnet den nächsten Punkt schrittweise, während er zur Mitte hochkommt", () => {
    const sections = points(3);
    // Unterkante des Bezugs (Höhe 680) liegt 150, 100, 50 px unter der Mitte
    const values = [150, 100, 50, 0].map((below) => accordionOpenness(sections, 0, options.center + below - 680, options)[1]);
    expect(values[0]).toBeGreaterThan(0);
    for (let index = 1; index < values.length; index += 1) expect(values[index]).toBeGreaterThan(values[index - 1]);
    expect(values[3]).toBe(1);
  });

  it("schliesst den vorherigen Punkt schrittweise, während er nach oben weggeht", () => {
    const sections = points(3);
    const values = [0, 50, 100, 250].map((past) => accordionOpenness(sections, 2, options.center - past, options)[1]);
    expect(values[0]).toBe(1);
    expect(values[1]).toBeLessThan(1);
    expect(values[2]).toBeLessThan(values[1]);
    expect(values[3]).toBe(0);
  });

  it("ergibt dieselbe Lage, egal welcher Punkt als Bezug dient - kein Sprung beim Wechsel", () => {
    const sections = [{ collapsed: 80, body: 600 }, { collapsed: 90, body: 200 }, { collapsed: 70, body: 900 }, { collapsed: 80, body: 300 }];
    // Bezug ist immer ein Punkt, der die Mitte enthält (oder an die Lücke grenzt)
    for (const anchorTop of [110, 150, 300, 390, 400, 410]) {
      const open = accordionOpenness(sections, 1, anchorTop, options);
      const tops = layout(sections, open, 1, anchorTop);
      // Jeder andere Punkt, der die Mittellinie enthält, liefert als Bezug dasselbe Ergebnis
      sections.forEach((section, index) => {
        const height = section.collapsed + open[index] * section.body;
        if (tops[index] > options.center || tops[index] + height < options.center) return;
        const again = accordionOpenness(sections, index, tops[index], options);
        again.forEach((value, i) => expect(value).toBeCloseTo(open[i], 6));
      });
    }
  });

  it("ändert sich stetig mit der Scrollposition", () => {
    const sections = points(4, 500);
    let previous = accordionOpenness(sections, 1, 0, options);
    for (let shift = 1; shift <= 400; shift += 1) {
      const open = accordionOpenness(sections, 1, -shift, options);
      open.forEach((value, index) => expect(Math.abs(value - previous[index])).toBeLessThan(0.02));
      previous = open;
    }
  });

  it("hat einen sinnvollen Standard-Weg", () => {
    expect(ACCORDION_RAMP).toBeGreaterThan(100);
  });
});

describe("createAccordionEngine", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  /** Dokument mit `count` Punkten; zählt, wie oft die Höhe jedes Elements gelesen wird. */
  function setup(count: number) {
    const reads = new Map<HTMLElement, number>();
    const measured = (element: HTMLElement, height: number) => {
      Object.defineProperty(element, "offsetHeight", {
        configurable: true,
        get: () => {
          reads.set(element, (reads.get(element) ?? 0) + 1);
          return height;
        },
      });
    };
    const container = document.createElement("div");
    Object.defineProperty(container, "clientHeight", { configurable: true, value: 800 });
    const inners: HTMLElement[] = [];
    for (let index = 0; index < count; index += 1) {
      const wrap = document.createElement("div");
      wrap.className = "protocol-doc-section-wrap";
      const section = document.createElement("section");
      section.className = "protocol-doc-section";
      section.id = `protocol-element-p${index}`;
      const body = document.createElement("div");
      body.className = "protocol-doc-section-body";
      const inner = document.createElement("div");
      body.append(inner);
      section.append(body);
      wrap.append(section);
      container.append(wrap);
      measured(section, 400);
      measured(body, 320);
      measured(inner, 320);
      inners.push(inner);
    }
    document.body.append(container);
    let resize: ResizeObserverCallback = () => {};
    vi.stubGlobal("ResizeObserver", class {
      constructor(callback: ResizeObserverCallback) { resize = callback; }
      observe() {}
      disconnect() {}
    });
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => frames.push(callback));
    vi.stubGlobal("cancelAnimationFrame", () => {});
    const runFrames = () => { while (frames.length) frames.shift()!(0); };
    return { container, inners, reads, runFrames, resize: (targets: HTMLElement[]) => resize(targets.map((target) => ({ target }) as ResizeObserverEntry), {} as ResizeObserver) };
  }

  it("misst bei einer Grössenänderung nur den geänderten Punkt neu", () => {
    const { container, inners, reads, runFrames, resize } = setup(6);
    const engine = createAccordionEngine(container, { onActiveChange: () => {} });
    // Erste Rechnung misst alle Punkte
    expect(reads.get(inners[5])).toBe(1);
    reads.clear();

    resize([inners[2]]);
    runFrames();

    expect(reads.get(inners[2])).toBe(1);
    for (const [element, count] of reads) {
      // Gelesen werden nur Punkt 2 selbst (Abschnitt, Rahmen, Inhalt)
      expect(element.closest("section")?.id, `${count} Lesungen ausserhalb von Punkt 2`).toBe("protocol-element-p2");
    }
    engine.destroy();
  });

  it("verwirft bei einer Änderung der Fenstergrösse weiterhin alle Masse", () => {
    const { container, inners, reads, runFrames } = setup(4);
    const engine = createAccordionEngine(container, { onActiveChange: () => {} });
    reads.clear();

    window.dispatchEvent(new Event("resize"));
    runFrames();

    for (const inner of inners) expect(reads.get(inner)).toBe(1);
    engine.destroy();
  });

  it("setzt Öffnungsgrad und Abstandshalter wie bisher als Custom Properties", () => {
    const { container, runFrames } = setup(4);
    const engine = createAccordionEngine(container, { onActiveChange: () => {} });
    runFrames();
    const sections = Array.from(container.querySelectorAll<HTMLElement>(".protocol-doc-section"));
    expect(sections[0].style.getPropertyValue("--open")).toBe("1.000");
    expect(container.style.getPropertyValue("--accordion-below")).toMatch(/px$/);
    engine.destroy();
    expect(container.style.getPropertyValue("--accordion-below")).toBe("");
  });

  it("überspringt den Inhalt ganz zugeklappter Punkte und behält ihre Höhe (S3)", () => {
    const { container, inners, runFrames } = setup(6);
    const engine = createAccordionEngine(container, { onActiveChange: () => {} });
    runFrames();
    // Punkt 0 offen, weit entfernte Punkte zu
    expect(inners[0].classList.contains(SKIPPED_CLASS)).toBe(false);
    expect(inners[5].classList.contains(SKIPPED_CLASS)).toBe(true);
    expect(inners[5].style.getPropertyValue("contain-intrinsic-height")).toBe("auto 320px");
    // Direkter Nachbar des Bezugs bleibt gerendert (Tab springt hinein)
    expect(inners[1].classList.contains(SKIPPED_CLASS)).toBe(false);
    // Sprungziel mit Autofokus: sofort und auch nach der nächsten Rechnung gerendert
    engine.reveal("p4");
    expect(inners[4].classList.contains(SKIPPED_CLASS)).toBe(false);
    engine.schedule();
    runFrames();
    expect(inners[4].classList.contains(SKIPPED_CLASS)).toBe(false);

    // Fenstergrösse: alles wieder rendern, neu messen, danach wieder überspringen
    window.dispatchEvent(new Event("resize"));
    expect(inners[5].classList.contains(SKIPPED_CLASS)).toBe(false);
    runFrames();
    expect(inners[5].classList.contains(SKIPPED_CLASS)).toBe(true);

    engine.destroy();
    // Ohne Akkordeon (abgeschaltet) bleibt nichts übersprungen
    for (const inner of inners) {
      expect(inner.classList.contains(SKIPPED_CLASS)).toBe(false);
      expect(inner.style.getPropertyValue("contain-intrinsic-height")).toBe("");
    }
  });
});
