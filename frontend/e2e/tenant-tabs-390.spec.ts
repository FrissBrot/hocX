import { expect, test } from "@playwright/test";

// Smartphone (390 px): Reiter (Tabs/RouteTabs, .tabs-list) auf Mandanten-Seiten überlappen nicht und
// machen die Seite nicht breiter als den Viewport - dieselbe Prüfung wie für die Admin-Konsole
// (admin-console.spec.ts, «Reiter überlappen nicht»), hier für Seiten mit Inhalts-Reitern.
const PAGES = [
  "/templates",
  "/elements",
  "/statistics",
  "/cycles",
  "/users",
  "/users/roles",
  "/users/security",
  "/tenant-settings/privacy",
  "/tenant-settings/retention",
  "/tenant-settings/domains",
  "/tenant-settings/verification",
  "/tenant-settings/links",
];

test.describe("Mandanten-Seiten: Reiter bei 390 px", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test.setTimeout(480_000);

  test("Reiterbeschriftungen überlappen nicht, Seite bleibt in 390 px", async ({ page }) => {
    const tooWide: string[] = [];
    const overlapping: string[] = [];
    for (const path of PAGES) {
      const response = await page.goto(path);
      expect(response?.status() ?? 200, path).toBeLessThan(500);
      await page.waitForLoadState("networkidle").catch(() => undefined);
      const width = await page.evaluate(() => document.documentElement.scrollWidth);
      if (width > 391) tooWide.push(`${path}: ${width}px`);
      const overlaps = await page.evaluate(() => {
        const found: string[] = [];
        for (const list of Array.from(document.querySelectorAll('[role="tablist"]'))) {
          const boxes = Array.from(list.querySelectorAll('[role="tab"]')).map((tab) => {
            const range = document.createRange();
            range.selectNodeContents(tab);
            return { label: (tab.textContent ?? "").trim(), rect: range.getBoundingClientRect() };
          }).filter((item) => item.rect.width > 0 && item.rect.height > 0);
          for (let i = 0; i < boxes.length; i += 1) {
            for (let j = i + 1; j < boxes.length; j += 1) {
              const a = boxes[i].rect;
              const b = boxes[j].rect;
              if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) {
                found.push(`${boxes[i].label} / ${boxes[j].label}`);
              }
            }
          }
        }
        return found;
      });
      if (overlaps.length) overlapping.push(`${path}: ${overlaps.join(", ")}`);
    }
    expect(overlapping, overlapping.join("\n")).toEqual([]);
    expect(tooWide, tooWide.join("\n")).toEqual([]);
  });
});
