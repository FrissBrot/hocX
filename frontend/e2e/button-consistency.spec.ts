import { test, expect, type Page } from "@playwright/test";

// Button-Regeln aus design/DESIGN.md (Abschnitt 7), im echten Browser geprüft statt nur im CSS:
// 1. Text-Buttons nebeneinander (gleicher Container) sind gleich hoch (Token --button-height).
// 2. Eine Nebenaktion (button-secondary) trägt nie die dunkle Primärfarbe - das war der
//    wiederkehrende «dunkle Button im hellen Design».
// Läuft in Hell und Dunkel, Desktop und Smartphone. Der Design-Checker
// (scripts/check-design-rules.py, Regeln button-hoehe/button-hintergrund) fängt das Gleiche
// schon im CSS ab; dieser Test sichert Fälle, die nur zur Laufzeit sichtbar werden.

const PAGES = ["/", "/files", "/photos", "/events", "/protocols", "/lists", "/todos", "/participants", "/users", "/fines", "/finances", "/templates", "/tenant-settings"];
const VARIANTS = ".button-primary, .button-secondary, .button-danger, .button-ghost";
const EXCLUDED = ".button-icon, .button-icon-soft, .button-icon-soft-sm, .button-pill";

type Finding = { page: string; theme: string; width: number; problem: string };

async function audit(page: Page): Promise<string[]> {
  return page.evaluate(
    ({ variants, excluded }) => {
      const problems: string[] = [];
      const probe = document.createElement("div");
      probe.style.background = "var(--primary)";
      document.body.appendChild(probe);
      const primary = getComputedStyle(probe).backgroundColor;
      probe.remove();
      const visible = (element: Element) => {
        const box = (element as HTMLElement).getBoundingClientRect();
        return box.width > 0 && box.height > 0 && getComputedStyle(element).visibility !== "hidden";
      };
      const label = (element: Element) => (element.textContent || element.getAttribute("aria-label") || element.className).toString().trim().slice(0, 40);
      const buttons = Array.from(document.querySelectorAll(variants)).filter((element) => !element.matches(excluded) && visible(element));
      const byParent = new Map<Element, Element[]>();
      for (const button of buttons) {
        const parent = button.parentElement;
        if (!parent || parent.closest("[data-button-sizes='mixed']")) continue;
        byParent.set(parent, [...(byParent.get(parent) ?? []), button]);
        if (button.matches(".button-secondary") && getComputedStyle(button).backgroundColor === primary) {
          problems.push(`Nebenaktion «${label(button)}» hat die Primärfarbe`);
        }
      }
      for (const group of byParent.values()) {
        if (group.length < 2) continue;
        const heights = group.map((button) => Math.round((button as HTMLElement).getBoundingClientRect().height));
        if (Math.max(...heights) - Math.min(...heights) > 1) {
          problems.push(`Ungleich hohe Buttons: ${group.map((button, index) => `«${label(button)}» ${heights[index]}px`).join(", ")}`);
        }
      }
      return problems;
    },
    { variants: VARIANTS, excluded: EXCLUDED }
  );
}

test("Buttons sind nebeneinander gleich hoch und Nebenaktionen nie dunkel", async ({ page }) => {
  test.setTimeout(420_000);
  const findings: Finding[] = [];
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ["light", "dark"]) {
      for (const path of PAGES) {
        await page.goto(path, { timeout: 60_000 });
        await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
        await page.reload({ timeout: 60_000 });
        await page.waitForLoadState("networkidle").catch(() => undefined);
        for (const problem of await audit(page)) findings.push({ page: path, theme, width, problem });
      }
    }
  }
  expect(findings, JSON.stringify(findings, null, 2)).toEqual([]);
});
