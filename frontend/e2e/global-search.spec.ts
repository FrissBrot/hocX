import { test, expect, type Page } from "@playwright/test";

// Globale Suche (Ctrl+K): Menüs/Einstellungen ohne Server, Personen über /api/search mit Sprung
// in die Bearbeitung, Ctrl+F springt auf Listenseiten ins Suchfeld der Liste.
// Mit SEARCH_SHOTS=<Ordner> entstehen zusätzlich Screenshots (Light/Dark, 1440 und 390 px).

const SHOTS = process.env.SEARCH_SHOTS;

async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
}

async function withTheme(page: Page, theme: "light" | "dark") {
  await page.addInitScript((value) => window.localStorage.setItem("hocx-theme", value), theme);
}

test("Ctrl+K findet Einstellungen und Personen und öffnet sie", async ({ page, request }) => {
  test.setTimeout(120_000);
  const name = `E2E Suchperson ${Date.now()}`;
  const created = await request.post("/api/participants", { data: { display_name: name, first_name: "E2E", last_name: "Suchperson" } });
  expect(created.ok(), await created.text()).toBeTruthy();
  const participant = await created.json();
  try {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await page.keyboard.press("Control+k");
    // Direkt lostippen, ohne ins Feld zu klicken: der Fokus muss schon im Suchfeld sein
    await page.keyboard.type("dsgvo");
    const dialog = page.getByRole("dialog", { name: "Suchen" });
    const input = dialog.getByRole("combobox");
    await expect(input).toBeFocused();
    await expect(input).toHaveValue("dsgvo");

    // Einstellung über einen Suchbegriff (nicht im Titel)
    // Seite und einzelne Einstellungen (Datenschutz-Statistik, -hinweis) erscheinen; Enter öffnet den ersten Treffer
    await expect(dialog.getByRole("option", { name: /Datenschutz/ }).first()).toBeVisible();
    await page.keyboard.press("Enter");
    // Erster Aufruf der Seite: der Next-Server des E2E-Stacks kompiliert sie erst (dauert >5 s)
    await expect(page).toHaveURL(/\/tenant-settings\/privacy(#[a-z-]+)?$/, { timeout: 30_000 });

    // Person aus der Datenbank, öffnet die Bearbeitung auf /participants
    await page.keyboard.press("Control+k");
    await input.fill(name);
    const option = dialog.getByRole("option", { name: new RegExp(name) });
    await expect(option).toBeVisible();
    await option.click();
    await expect(page).toHaveURL(/\/participants$/, { timeout: 30_000 });
    await expect
      .poll(() => page.getByRole("dialog").locator("input").evaluateAll((inputs, wanted) => inputs.some((input) => (input as HTMLInputElement).value === wanted), name))
      .toBe(true);
  } finally {
    await request.delete(`/api/participants/${participant.id}`);
  }
});

test("Ctrl+K findet einzelne Einstellungen, Rollen und Elemente", async ({ page, request }) => {
  test.setTimeout(120_000);
  const title = `E2E Suchelement ${Date.now()}`;
  const created = await request.post("/api/element-definitions", { data: { title, blocks: [] } });
  expect(created.ok(), await created.text()).toBeTruthy();
  const element = await created.json();
  try {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    const dialog = page.getByRole("dialog", { name: "Suchen" });

    // Einzelne Einstellung: Reiter der Bussen-Konfiguration
    await page.keyboard.press("Control+k");
    await page.keyboard.type("Bussen-Tarife");
    await dialog.getByRole("option", { name: /Bussen-Tarife/ }).click();
    await expect(page).toHaveURL(/\/fine-settings\?tab=tariffs$/, { timeout: 30_000 });
    await expect(page.getByRole("tab", { name: /Tarife/ })).toHaveAttribute("aria-selected", "true");

    // Standardrolle über ihren übersetzten Namen
    await page.keyboard.press("Control+k");
    await page.keyboard.type("Kassier");
    await dialog.getByRole("option", { name: /Kassier/ }).first().click();
    await expect(page).toHaveURL(/\/users\/roles\?role=/, { timeout: 30_000 });

    // Element der Bibliothek
    await page.keyboard.press("Control+k");
    await page.keyboard.type(title);
    await dialog.getByRole("option", { name: new RegExp(title) }).click();
    await expect(page).toHaveURL(new RegExp(`/elements\\?open=${element.id}`), { timeout: 30_000 });
  } finally {
    await request.delete(`/api/element-definitions/${element.id}`);
  }
});

test("Ctrl+F springt auf Listenseiten ins Suchfeld der Liste", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/participants");
  const listSearch = page.locator(".shell-content .search-input input").first();
  await expect(listSearch).toBeVisible();
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("Control+f");
  await expect(listSearch).toBeFocused();

  // Aus dem Suchfenster heraus in der Liste suchen
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog", { name: "Suchen" });
  await dialog.getByRole("combobox").fill("anna");
  await dialog.getByRole("option", { name: /In dieser Liste/ }).click();
  await expect(listSearch).toHaveValue("anna");
  await expect(listSearch).toBeFocused();
});

for (const theme of ["light", "dark"] as const) {
  test(`Suchfenster sieht in ${theme} auf Desktop und Handy richtig aus`, async ({ page }) => {
    test.skip(!SHOTS, "nur mit SEARCH_SHOTS");
    await withTheme(page, theme);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/participants");
    await shot(page, `${theme}-1440-topbar`);
    await page.keyboard.press("Control+k");
    const dialog = page.getByRole("dialog", { name: "Suchen" });
    await dialog.getByRole("combobox").fill("an");
    await expect(dialog.getByRole("option").first()).toBeVisible();
    await page.waitForTimeout(600);
    await shot(page, `${theme}-1440-palette`);

    await page.keyboard.press("Escape");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await page.getByRole("button", { name: "Mehr" }).click();
    await shot(page, `${theme}-390-more`);
    await page.getByRole("button", { name: /Suchen/ }).first().click();
    await dialog.getByRole("combobox").fill("bus");
    await page.waitForTimeout(600);
    await shot(page, `${theme}-390-palette`);
  });
}
