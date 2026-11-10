import { test, expect } from "@playwright/test";

// Landing Page: Funktionsvergleich direkt aus dem Preiskatalog der Datenbank (GET
// /api/public/plan-comparison). Prüft, dass die Tabelle genau diese Abos und Features zeigt, und
// legt Screenshots (Light/Dark, 1440 und 390 px) ab.

test("Landing Page: Vergleichstabelle zeigt Abos und Features aus der Datenbank", async ({ page }) => {
  test.setTimeout(180_000);
  const comparison = await (await page.request.get("/api/public/plan-comparison")).json();
  test.skip(comparison.plans.length === 0, "kein buchbarer Plan im E2E-Katalog");
  for (const theme of ["light", "dark"]) {
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto("/website");
      await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
      await page.reload();
      const table = page.getByRole("table", { name: "Funktionen und Abos im Vergleich" });
      await expect(table).toBeVisible({ timeout: 60_000 });
      const heads = table.locator("thead th.ws-compare-plan");
      await expect(heads).toHaveCount(comparison.plans.length);
      for (const plan of comparison.plans) await expect(heads.filter({ hasText: plan.name })).toHaveCount(1);
      for (const feature of comparison.features) await expect(table.getByRole("rowheader", { name: new RegExp(feature.name) })).toBeVisible();
      await page.locator("#vergleich").scrollIntoViewIfNeeded();
      await page.locator("#vergleich").screenshot({ path: `test-results/website-comparison-${theme}-${width}.png` });
    }
  }
});
