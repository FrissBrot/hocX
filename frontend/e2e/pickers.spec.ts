import { test, expect } from "@playwright/test";

// Auswahlliste (Select), Kalender (DateInput) und Farbwähler (ColorInput) im hocX-Look statt der
// Oberfläche des Betriebssystems. Legt Screenshots (Light/Dark, 1440 px) ab.

for (const theme of ["light", "dark"]) {
  test(`Picker im hocX-Look (${theme})`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/events");
    await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
    await page.reload();

    // Kalender im Termin-Dialog
    await page.getByRole("button", { name: /Termin/ }).first().click();
    const dialog = page.getByRole("dialog").first();
    await dialog.getByRole("button", { name: "Datum wählen" }).first().click();
    const calendar = page.getByRole("dialog", { name: "Kalender" });
    await expect(calendar).toBeVisible();
    await expect(calendar.getByRole("button", { pressed: true }).or(calendar.locator("[aria-current=date]"))).toHaveCount(1, { timeout: 5_000 }).catch(() => undefined);
    await page.screenshot({ path: `test-results/pickers-calendar-${theme}-1440.png` });
    await page.keyboard.press("Escape");
    await expect(calendar).toBeHidden();

    // Auswahlliste im Brand Studio
    await page.goto("/documents/brand");
    const select = page.getByRole("combobox").first();
    await expect(select).toBeVisible({ timeout: 60_000 });
    await select.click();
    const list = page.getByRole("listbox");
    await expect(list).toBeVisible();
    await page.screenshot({ path: `test-results/pickers-select-${theme}-1440.png` });
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Escape");
    await expect(list).toBeHidden();

    // Farbwähler
    await page.getByRole("button", { name: "Hauptfarbe" }).click();
    const picker = page.getByRole("dialog", { name: "Hauptfarbe" });
    await expect(picker).toBeVisible();
    await page.screenshot({ path: `test-results/pickers-color-${theme}-1440.png` });
  });
}

// Abgabebox: Sprachwahl mit derselben Liste (abgabebox-frontend/components/ui/select.tsx)
for (const colorScheme of ["light", "dark"] as const) {
  test(`Abgabebox: Sprachwahl im hocX-Look (${colorScheme})`, async ({ browser }) => {
    const context = await browser.newContext({ baseURL: process.env.E2E_ABGABEBOX_BASE_URL, storageState: undefined, colorScheme, viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    try {
      await page.goto("/verify");
      const select = page.getByRole("combobox").first();
      await expect(select).toBeVisible({ timeout: 60_000 });
      await select.click();
      const list = page.getByRole("listbox");
      await expect(list).toBeVisible();
      await expect(list.getByRole("option")).not.toHaveCount(0);
      await page.screenshot({ path: `test-results/pickers-abgabebox-${colorScheme}-1440.png` });
      await page.keyboard.press("Escape");
      await expect(list).toBeHidden();
    } finally {
      await context.close();
    }
  });
}
