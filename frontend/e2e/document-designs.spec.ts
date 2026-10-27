import { test, expect } from "@playwright/test";

// Designs (Alpin, Kreide …) im Dialog «Neue Vorlage» und Darstellung einzelner Bausteine im
// Designer einer Sitzungsvorlage. Legt Screenshots (Light/Dark) ab. Auf dem Handy zeigen
// Dokument-Studio und Vorlagen-Editor nur den Hinweis, sie am Computer zu öffnen - daher nur
// Desktop-Breite.

test("Neue Vorlage: Design-Galerie für Protokolle", async ({ page }) => {
  test.setTimeout(180_000);
  for (const theme of ["light", "dark"]) {
    for (const width of [1440]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto("/documents/protocols");
      await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
      await page.reload();
      await page.getByRole("button", { name: "Neue Vorlage" }).click();
      const dialog = page.getByRole("dialog", { name: "Neue Vorlage" });
      await dialog.getByRole("radio", { name: /Alpin/ }).click();
      await expect(dialog.getByRole("textbox", { name: "Name" })).toHaveValue("Alpin");
      // Vorschaubilder laden lazy: erst fotografieren, wenn alle da sind
      await expect.poll(() => dialog.locator("img").evaluateAll((images) => images.every((image) => (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0))).toBe(true);
      await page.screenshot({ path: `test-results/document-designs-create-${theme}-${width}.png`, fullPage: true });
      await dialog.getByRole("button", { name: "Abbrechen" }).click();
      await expect(dialog).toBeHidden();
    }
  }
});

test("Designer: einen Baustein des Protokollinhalts anders darstellen", async ({ page }) => {
  test.setTimeout(240_000);
  const templates = await (await page.request.get("/api/templates")).json();
  const copy = await (await page.request.post(`/api/templates/${templates[0].id}/duplicate`, { data: { name: `E2E Designs ${Date.now()}` } })).json();
  try {
    const own = await page.request.post(`/api/document-studio/session-templates/${copy.id}/designs/protocol`, { data: { name: `E2E Designs ${Date.now()}` } });
    expect(own.ok()).toBeTruthy();
    for (const theme of ["light", "dark"]) {
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto(`/templates/${copy.id}`);
      await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
      await page.reload();
      await page.getByRole("tab", { name: /^PDF/ }).click();
      // Der Designer startet im Modus «Einfach» (danach gemerkt); die Struktur gibt es in der
      // freien Gestaltung
      await expect(page.getByRole("textbox", { name: "Name der Vorlage" })).toBeVisible({ timeout: 60_000 });
      const advanced = page.getByRole("button", { name: "Erweitert öffnen" });
      if (await advanced.isVisible()) await advanced.click();
      await page.getByRole("tab", { name: "Struktur" }).click();
      const left = page.getByRole("complementary", { name: "Bausteine" });
      const blocks = left.getByRole("group", { name: "Bausteine der Sitzungsvorlage" });
      await expect(blocks).toBeVisible({ timeout: 60_000 });
      await blocks.getByRole("button").first().click();
      const panel = page.getByRole("complementary", { name: "Eigenschaften" });
      await expect(panel.getByText(/^Traktandum:/)).toBeVisible();
      await page.screenshot({ path: `test-results/document-designs-block-${theme}-1440.png` });
    }
  } finally {
    await page.request.delete(`/api/templates/${copy.id}`);
  }
});

test("Aktionsmenü einer Karte am unteren Fensterrand klappt sichtbar nach oben auf", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 700 });
  await page.goto("/documents/protocols");
  const trigger = page.getByRole("button", { name: /^Aktionen für/ }).first();
  await expect(trigger).toBeVisible({ timeout: 60_000 });
  // Karte so scrollen, dass ihr Menü-Knopf knapp über dem unteren Fensterrand steht
  await trigger.evaluate((element) => window.scrollBy(0, element.getBoundingClientRect().bottom - window.innerHeight + 24));
  await trigger.click();
  const menu = page.getByRole("menu");
  await expect(menu).toBeVisible();
  const box = await menu.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height).toBeLessThanOrEqual(700);
  await expect(menu.getByRole("menuitem").first()).toBeInViewport();
});
