import { describe, expect, it } from "vitest";

import { scrollDuration, sectionScrollTarget, wheelStyle } from "./document-scroll";

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

describe("wheelStyle", () => {
  const view = { scrollTop: 0, viewport: 1000 };

  it("lässt den Punkt auf der Mittellinie unverändert", () => {
    expect(wheelStyle({ ...view, top: 400, height: 300 }).transform).toBe("");
  });

  it("kippt Punkte unterhalb nach hinten und oberhalb nach vorne weg", () => {
    const below = wheelStyle({ ...view, top: 800, height: 100 });
    expect(below.transformOrigin).toBe("50% 0%");
    expect(below.transform).toMatch(/rotateX\(-/);
    const above = wheelStyle({ ...view, top: 0, height: 100 });
    expect(above.transformOrigin).toBe("50% 100%");
    expect(above.transform).toMatch(/rotateX\(\d/);
  });

  it("erreicht ab 60 % der Höhe die volle Stärke", () => {
    const far = wheelStyle({ ...view, top: 1200, height: 100 });
    expect(far.transform).toBe("perspective(1400px) rotateX(-24.00deg) scale(0.8800)");
    expect(far.opacity).toBe("0.400");
    expect(far.filter).toBe("blur(1.40px) grayscale(0.40)");
  });
});

it("skaliert die Sprungdauer mit der Distanz", () => {
  expect(scrollDuration(0)).toBe(260);
  expect(scrollDuration(-400)).toBe(360);
  expect(scrollDuration(5000)).toBe(620);
});
