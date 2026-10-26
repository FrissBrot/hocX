import { test, expect, type Page } from "@playwright/test";

// Element-Editor: ein Formular für Anlegen und Bearbeiten, gemeinsamer Terminfilter und
// Matrix-Designer. Prüft den Ablauf und legt Screenshots (Light/Dark) ab. Auf dem Handy zeigt
// /elements nur den Hinweis, den Bereich am Computer zu öffnen - daher nur Desktop-Breite.

async function openNewElement(page: Page, typeName: string) {
  const picker = page.getByRole("dialog", { name: "Blocktyp auswählen" });
  // `next dev` kompiliert Routen nach und kann einen offenen Dialog per HMR schliessen.
  await expect(async () => {
    if (!(await picker.isVisible())) await page.getByRole("button", { name: "Neuer Baustein", exact: true }).click();
    await expect(picker).toBeVisible({ timeout: 5_000 });
    await picker.getByRole("button", { name: new RegExp(`^${typeName}`) }).click({ timeout: 5_000 });
  }).toPass({ timeout: 30_000 });
  const dialog = page.getByRole("dialog", { name: "Element anlegen" });
  await expect(dialog).toBeVisible();
  return dialog;
}

test("Element-Editor: Anlegen, Bearbeiten und Matrix-Designer", async ({ page }) => {
  test.setTimeout(180_000);
  const title = `Termine ${Date.now()}`;
  await page.goto("/elements");

  for (const theme of ["light", "dark"]) {
    for (const width of [1440]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
      await page.reload();
      const dialog = await openNewElement(page, "Terminliste");
      await expect(dialog.getByLabel("Welche Termine?")).toHaveValue("future");
      await page.screenshot({ path: `test-results/elements-create-${theme}-${width}.png`, fullPage: true });
      // Kann per HMR schon geschlossen sein (siehe openNewElement).
      if (await dialog.isVisible()) await dialog.getByRole("button", { name: "Abbrechen" }).click({ timeout: 5_000 }).catch(() => undefined);
      await expect(dialog).toBeHidden();
    }
  }

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.evaluate(() => localStorage.setItem("hocx-theme", "light"));
  await page.reload();
  const create = await openNewElement(page, "Terminliste");
  await create.getByRole("textbox", { name: "Elementtitel", exact: true }).fill(title);
  await create.getByLabel("Welche Termine?").selectOption("window");
  await create.getByRole("button", { name: "Element anlegen" }).click();

  const definition = page.getByRole("dialog", { name: `Element bearbeiten: ${title}` });
  // `next dev` baut in der CI parallel Routen des zweiten Workers und kann die Seite per Fast
  // Refresh neu montieren: offene Dialoge sind dann weg, die Liste zeigt den Stand vom Laden.
  // Dann Seite neu laden und das Element über seine Zeile wieder öffnen.
  async function ensureDefinitionOpen() {
    if (await definition.isVisible()) return;
    for (const dialog of await page.getByRole("dialog").all()) await dialog.press("Escape").catch(() => undefined);
    await page.reload();
    await page.getByRole("row", { name: new RegExp(title) }).click({ timeout: 10_000 });
    await expect(definition).toBeVisible({ timeout: 5_000 });
  }

  const edit = page.getByRole("dialog", { name: /Block bearbeiten/ });
  await expect(async () => {
    await ensureDefinitionOpen();
    if (!(await edit.isVisible())) await definition.getByRole("button", { name: "Bearbeiten" }).first().click({ timeout: 5_000 });
    await expect(edit).toBeVisible({ timeout: 5_000 });
    // Gleiches Formular wie beim Anlegen: Verhalten und gespeicherter Zeitraum sind da.
    await expect(edit.getByRole("checkbox", { name: /Im PDF ausgeben/ })).toBeVisible({ timeout: 5_000 });
    await expect(edit.getByLabel("Welche Termine?")).toHaveValue("window", { timeout: 5_000 });
  }).toPass({ timeout: 60_000 });
  await page.screenshot({ path: "test-results/elements-edit-light-1440.png", fullPage: true });
  if (await edit.isVisible()) await edit.getByRole("button", { name: "Abbrechen" }).click({ timeout: 5_000 }).catch(() => undefined);

  const picker = page.getByRole("dialog", { name: "Blocktyp auswählen" });
  const blockDialog = page.getByRole("dialog", { name: "Block anlegen" });
  const designer = page.getByRole("dialog", { name: "Matrix konfigurieren" });
  await expect(async () => {
    if (!(await designer.isVisible())) {
      if (!(await blockDialog.isVisible())) {
        await ensureDefinitionOpen();
        await definition.getByRole("button", { name: "Neuer Block" }).click({ timeout: 5_000 });
        await picker.getByRole("button", { name: /^Matrix/ }).click({ timeout: 5_000 });
      }
      await blockDialog.getByRole("button", { name: "Matrix konfigurieren" }).click({ timeout: 5_000 });
    }
    await expect(designer).toBeVisible({ timeout: 5_000 });
    await designer.getByRole("button", { name: "+ Spalte" }).click({ timeout: 5_000 });
    await designer.locator(".matrix-designer-row-head").first().click({ timeout: 5_000 });
    await designer.getByLabel("Zeilentyp").selectOption("events", { timeout: 5_000 });
    await page.screenshot({ path: "test-results/elements-matrix-light-1440.png", fullPage: true });
    await designer.getByRole("button", { name: "Übernehmen" }).click({ timeout: 5_000 });
    await expect(designer).toBeHidden({ timeout: 5_000 });
    await blockDialog.getByRole("button", { name: "Block anlegen" }).click({ timeout: 5_000 });
    await expect(definition.getByText("Matrix", { exact: true })).toBeVisible({ timeout: 5_000 });
  }).toPass({ timeout: 90_000 });
});
