import { test, expect } from "@playwright/test";

// Dokument-Designer, Modus «Einfach»: drei Schritte links, Vorschau als Arbeitsfläche. Ein Klick
// in die Vorschau öffnet den passenden Baustein. Legt Screenshots (Light/Dark, 1440 px) ab.

test("Einfach-Modus: Stil wählen und Baustein per Klick in der Vorschau öffnen", async ({ page }) => {
  test.setTimeout(240_000);
  const created = await page.request.post("/api/document-studio/examples/atlas/import", { data: { name: `E2E Einfach ${Date.now()}` } });
  expect(created.ok()).toBeTruthy();
  const template = await created.json();
  try {
    for (const theme of ["light", "dark"]) {
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto(`/documents/templates/${template.id}`);
      await page.evaluate((value) => {
        localStorage.setItem("hocx-theme", value);
        localStorage.removeItem("hocx.documentStudio.mode");
      }, theme);
      await page.reload();
      const panel = page.getByRole("complementary", { name: "Dokument einfach gestalten" });
      await expect(panel).toBeVisible({ timeout: 60_000 });
      await expect(page.getByRole("button", { name: "Erweitert öffnen" })).toBeVisible();
      // Vorschau mit Klickflächen
      const hit = page.locator(".studio-preview-hit").first();
      await expect(hit).toBeAttached({ timeout: 90_000 });
      await page.screenshot({ path: `test-results/designer-simple-${theme}-1440.png` });

      await panel.getByRole("radio", { name: "Siegel" }).click();
      await page.locator(".studio-preview-hit").last().click();
      await expect(panel.locator(".studio-simple-block-open")).toHaveCount(1);
      await page.screenshot({ path: `test-results/designer-simple-picked-${theme}-1440.png` });
      await panel.getByRole("radiogroup", { name: "Stil" }).getByRole("radio", { name: "Wie im Profil" }).click();
    }
  } finally {
    await page.request.delete(`/api/document-templates/${template.id}`);
  }
});
