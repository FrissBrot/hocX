import { expect, test, type Locator, type Page } from "@playwright/test";

import { authFiles } from "./auth";

// 1.6.1: Wechsel zwischen Desktop- und Mobilansicht (gedrehtes Tablet, schmal gezogenes Fenster,
// Breakpoint 900 px) darf die Seite nicht neu mounten. Vorher tauschte die AppShell den ganzen Baum
// (Sidebar-Rahmen <-> Mobile-Shell) und ResponsiveView die Seitenvariante: halb ausgefüllte
// Eingaben, offene Dialoge und der Schritt im Datei-Import gingen verloren.
test.use({ storageState: authFiles.admin });

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };

/** Breite ändern und warten, bis die Shell umgeschaltet hat (Rahmen bzw. Tableiste). */
async function resizeTo(page: Page, size: { width: number; height: number }) {
  await page.setViewportSize(size);
  if (size.width > 900) {
    await expect(page.locator(".app-frame")).toBeVisible();
    await expect(page.locator(".mobile-shell")).toHaveCount(0);
  } else {
    await expect(page.locator(".mobile-tabbar")).toBeVisible();
    await expect(page.locator(".app-frame")).toHaveCount(0);
  }
}

/** Merkt sich den DOM-Knoten - ist er nach dem Wechsel nicht mehr im Dokument, wurde neu gemountet. */
async function markNode(locator: Locator) {
  await locator.evaluate((node) => {
    (window as unknown as { __shellMarker?: Element }).__shellMarker = node;
  });
}

async function markedNodeStillMounted(page: Page): Promise<boolean> {
  return page.evaluate(() => Boolean((window as unknown as { __shellMarker?: Element }).__shellMarker?.isConnected));
}

test.describe("Wechsel Desktop/Mobil behält den Seitenzustand", () => {
  test.setTimeout(120_000);

  test("Personenseite: Eingabe und Fokus bleiben bei 1440 -> 390 -> 1440 erhalten", async ({ page, request }) => {
    const name = `Shell-Wechsel ${Date.now()}`;
    const response = await request.post("/api/participants", { data: { display_name: name } });
    expect(response.ok(), await response.text()).toBeTruthy();
    const participant = await response.json();
    try {
      await page.setViewportSize(DESKTOP);
      await page.goto(`/participants/${participant.id}`);
      const field = page.getByLabel("Anzeigename");
      await expect(field).toHaveValue(name, { timeout: 30_000 });
      await markNode(field);
      await field.fill(`${name} geändert`);

      await resizeTo(page, MOBILE);
      await expect(page.getByLabel("Anzeigename")).toHaveValue(`${name} geändert`);
      await expect(page.getByLabel("Anzeigename")).toBeFocused();
      expect(await markedNodeStillMounted(page)).toBe(true);

      await resizeTo(page, DESKTOP);
      await expect(page.getByLabel("Anzeigename")).toHaveValue(`${name} geändert`);
      await expect(page.getByLabel("Anzeigename")).toBeFocused();
      expect(await markedNodeStillMounted(page)).toBe(true);
      // Tastatur geht weiter ins selbe Feld
      await page.keyboard.type("!");
      await expect(page.getByLabel("Anzeigename")).toHaveValue(`${name} geändert!`);
    } finally {
      await request.delete(`/api/participants/${participant.id}`);
    }
  });

  test("Datei-Import: gewählte Quelle und Optionen bleiben erhalten", async ({ page }) => {
    await page.setViewportSize(DESKTOP);
    await page.goto("/files/import");
    await expect(page.getByRole("heading", { name: "Dateien importieren" })).toBeVisible({ timeout: 30_000 });
    const folder = page.getByRole("radio", { name: /Ordner hochladen/ });
    // Läuft ein Import eines früheren Laufs, gibt es keine Quellenwahl - dann nur den Knoten prüfen.
    const sourceStep = (await folder.count()) > 0;
    await markNode(page.getByRole("heading", { name: "Dateien importieren" }));
    if (sourceStep) {
      await folder.click();
      await page.getByLabel("Dateitypen").selectOption("images");
      await page.getByRole("checkbox", { name: "GPS-Daten der Bilder übernehmen" }).uncheck();
    }

    for (const size of [MOBILE, DESKTOP]) {
      await resizeTo(page, size);
      expect(await markedNodeStillMounted(page)).toBe(true);
      if (sourceStep) {
        await expect(page.getByRole("radio", { name: /Ordner hochladen/ })).toHaveAttribute("aria-checked", "true");
        await expect(page.getByLabel("Dateitypen")).toHaveValue("images");
        await expect(page.getByRole("checkbox", { name: "GPS-Daten der Bilder übernehmen" })).not.toBeChecked();
      }
    }
  });

  test("Pendenz-Dialog: offener Dialog und Eingabe bleiben erhalten, danach folgt die Mobilansicht", async ({ page }) => {
    const task = `Shell-Wechsel Pendenz ${Date.now()}`;
    await page.setViewportSize(DESKTOP);
    await page.goto("/todos");
    await page.getByRole("button", { name: "+ Pendenz" }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Neue Pendenz")).toBeVisible({ timeout: 30_000 });
    await dialog.getByRole("textbox", { name: "Aufgabe" }).fill(task);

    await resizeTo(page, MOBILE);
    await expect(dialog.getByRole("textbox", { name: "Aufgabe" })).toHaveValue(task);
    await resizeTo(page, DESKTOP);
    await expect(dialog.getByRole("textbox", { name: "Aufgabe" })).toHaveValue(task);

    // Aufgeschobener Wechsel: bei 390 px mit offenem Dialog bleibt die Desktop-Variante stehen,
    // nach dem Schliessen kommt die Mobil-Variante der Seite.
    await resizeTo(page, MOBILE);
    await expect(dialog.getByRole("textbox", { name: "Aufgabe" })).toHaveValue(task);
    await dialog.getByRole("button", { name: "Abbrechen" }).click();
    const discard = page.getByRole("alertdialog");
    if (await discard.isVisible().catch(() => false)) {
      await discard.getByRole("button").last().click();
    }
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.locator(".mobile-shell-content .mobile-page")).toBeVisible();
  });

  test("Termin-Dialog: Titel bleibt beim Wechsel erhalten", async ({ page }) => {
    const title = `Shell-Wechsel Termin ${Date.now()}`;
    await page.setViewportSize(DESKTOP);
    await page.goto("/events");
    await page.getByRole("button", { name: /Termin$/ }).first().click();
    const dialog = page.getByRole("dialog").filter({ has: page.getByRole("tab", { name: "Übersicht" }) });
    await expect(dialog).toBeVisible({ timeout: 30_000 });
    await dialog.getByLabel("Titel", { exact: true }).fill(title);

    await resizeTo(page, MOBILE);
    await expect(dialog.getByLabel("Titel", { exact: true })).toHaveValue(title);
    await resizeTo(page, DESKTOP);
    await expect(dialog.getByLabel("Titel", { exact: true })).toHaveValue(title);
  });
});
