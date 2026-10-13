import { test, expect, type Page } from "@playwright/test";

// Element-Editor: ein Formular für Anlegen und Bearbeiten, gemeinsamer Terminfilter und
// Matrix-Designer. Prüft den Ablauf und legt Screenshots (Light/Dark) ab. Auf dem Handy zeigt
// /elements nur den Hinweis, den Bereich am Computer zu öffnen - daher nur Desktop-Breite.

async function openNewElement(page: Page, typeName: string) {
  const picker = page.getByRole("dialog", { name: "Blocktyp auswählen" });
  // `next dev` kompiliert Routen nach und kann einen offenen Dialog per HMR schliessen.
  await expect(async () => {
    if (!(await picker.isVisible())) await page.getByRole("button", { name: "Neues Element", exact: true }).click();
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
  await expect(definition).toBeVisible();
  await definition.getByRole("button", { name: "Bearbeiten" }).first().click();
  const edit = page.getByRole("dialog", { name: /Block bearbeiten/ });
  await expect(edit).toBeVisible();
  // Gleiches Formular wie beim Anlegen: Verhalten und gespeicherter Zeitraum sind da.
  await expect(edit.getByRole("checkbox", { name: /Im PDF ausgeben/ })).toBeVisible();
  await expect(edit.getByLabel("Welche Termine?")).toHaveValue("window");
  await page.screenshot({ path: "test-results/elements-edit-light-1440.png", fullPage: true });
  await edit.getByRole("button", { name: "Abbrechen" }).click();

  await definition.getByRole("button", { name: "Neuer Block" }).click();
  const picker = page.getByRole("dialog", { name: "Blocktyp auswählen" });
  await picker.getByRole("button", { name: /^Matrix/ }).click();
  const blockDialog = page.getByRole("dialog", { name: "Block anlegen" });
  await blockDialog.getByRole("button", { name: "Matrix konfigurieren" }).click();
  const designer = page.getByRole("dialog", { name: "Matrix konfigurieren" });
  await expect(designer).toBeVisible();
  await designer.getByRole("button", { name: "+ Spalte" }).click();
  await designer.locator(".matrix-designer-row-head").first().click();
  await designer.getByLabel("Zeilentyp").selectOption("events");
  await page.screenshot({ path: "test-results/elements-matrix-light-1440.png", fullPage: true });
  await designer.getByRole("button", { name: "Übernehmen" }).click();
  await expect(designer).toBeHidden();
  await blockDialog.getByRole("button", { name: "Block anlegen" }).click();
  await expect(definition.getByText("Matrix", { exact: true })).toBeVisible();
});
