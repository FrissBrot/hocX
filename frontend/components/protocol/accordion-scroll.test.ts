import { describe, expect, it } from "vitest";

import { ACCORDION_RAMP, accordionOpenness, type AccordionMetrics } from "./accordion-scroll";

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
