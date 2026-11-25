import { test, expect, type APIRequestContext, type Page } from "@playwright/test";

import { authFiles } from "./auth";

// Datei-Import aus Google Drive (drive.file + Google Picker) und Google Fotos (Photos Picker API) mit
// dem nachgebauten Google des E2E-Stacks (CLOUD_IMPORT_FAKE_PROVIDERS, Backend
// services/cloud_import/fake_google.py; der Picker-Loader kommt dort von /api/cloud-import/fake-google).
// Prüft auch, dass die gelockerte CSP nur auf der Picker-Seite gilt. Screenshots hell/dunkel 1440/390 px.
test.use({ storageState: authFiles.admin });

const OPEN = ["draft", "listing", "ready", "queued", "running", "needs_reauth"];

async function cancelOpenImports(api: APIRequestContext) {
  const jobs = (await (await api.get("/api/cloud-import/jobs")).json()) as { id: string; status: string }[];
  for (const job of jobs.filter((entry) => OPEN.includes(entry.status))) {
    await api.post(`/api/cloud-import/jobs/${job.id}/cancel`);
  }
  await expect
    .poll(async () => ((await (await api.get("/api/cloud-import/jobs")).json()) as { status: string }[]).some((job) => job.status === "cancel_requested"), { timeout: 60_000 })
    .toBe(false);
}

async function shoot(page: Page, name: string) {
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width > 600 ? 900 : 844 });
      await page.waitForTimeout(150);
      await page.screenshot({ path: `test-results/cloud-google/${name}-${theme}-${width}.png`, fullPage: true });
    }
  }
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
  await page.setViewportSize({ width: 1440, height: 900 });
}

async function signIn(page: Page, scenario: "anna" | "work" | "noscope" | "cancel") {
  await expect(page.getByRole("heading", { name: /Test-Anmeldung/ })).toBeVisible();
  await page.locator(`button[data-scenario="${scenario}"]`).click();
  await page.waitForURL(/\/files\/import/);
}

function directive(csp: string, name: string): string {
  return csp.split("; ").find((entry) => entry.startsWith(`${name} `)) ?? "";
}

async function choose(page: Page, provider: RegExp) {
  await page.goto("/files/import");
  await expect(page.getByRole("heading", { name: "Dateien importieren" })).toBeVisible();
  await page.getByRole("radio", { name: provider }).click();
  await page.getByRole("button", { name: "Weiter", exact: true }).click();
}

test("Google Drive: anmelden, im Picker wählen, Google-Formate importieren", async ({ page, request }) => {
  test.setTimeout(300_000);
  await cancelOpenImports(request);

  const wizard = await page.goto("/files/import");
  // Der Wizard selbst bleibt bei der strengen CSP
  expect(directive(wizard?.headers()["content-security-policy"] ?? "", "frame-src")).toBe("frame-src 'none'");

  await choose(page, /Google Drive/);
  await expect(page.getByRole("heading", { name: "Mit Google Drive verbinden" })).toBeVisible();
  await page.getByRole("button", { name: "Bei Google Drive anmelden" }).click();
  await signIn(page, "anna");
  await expect(page.getByText("Verbunden als anna@verein.test", { exact: true })).toBeVisible({ timeout: 30_000 });
  expect(page.url()).not.toContain("cloud_finish");
  await shoot(page, "01-drive-connected");

  // Per Tastatur zur Picker-Seite (voller Seitenwechsel)
  const choose_ = page.getByRole("link", { name: "In Google Drive auswählen" });
  await choose_.focus();
  const pickerResponse = page.waitForResponse((response) => new URL(response.url()).pathname === "/files/import/google-picker");
  await page.keyboard.press("Enter");
  const picker = await pickerResponse;
  const csp = picker.headers()["content-security-policy"] ?? "";
  expect(directive(csp, "frame-src")).toBe("frame-src https://docs.google.com https://drive.google.com");
  expect(directive(csp, "script-src")).toMatch(/'nonce-[^']+'.*https:\/\/apis\.google\.com/);
  expect(directive(csp, "frame-ancestors")).toBe("frame-ancestors 'none'");
  await expect(page.getByRole("heading", { name: "Dateien aus Google Drive auswählen" })).toBeVisible();

  // Nachgebauter Picker: erst abbrechen, dann erneut öffnen und wählen
  const dialog = page.getByRole("dialog", { name: "Google Picker (Test)" });
  await expect(dialog).toBeVisible({ timeout: 30_000 });
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByText("Die Auswahl wurde geschlossen, ohne Dateien zu übernehmen.")).toBeVisible();
  await shoot(page, "02-picker-page");
  await page.getByRole("button", { name: "Google-Auswahl öffnen" }).click();
  for (const name of ["Protokoll GV", "Budget 2026", "Statuten.pdf", "Anmeldung Lager"]) {
    await dialog.getByLabel(name).check();
  }
  await dialog.getByRole("button", { name: "Select" }).click();

  // Zurück im Wizard (wieder strenge CSP), Auflisten im Hintergrund, Regeln, Import
  await page.waitForURL(/\/files\/import\?job=/);
  const start = page.getByRole("button", { name: "Import starten" });
  await expect(start).toBeVisible({ timeout: 120_000 });
  await expect(start).toBeEnabled({ timeout: 30_000 });
  await shoot(page, "03-drive-rules");
  await start.click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Import starten" }).click();

  await expect(page.getByText(/Import abgeschlossen/)).toBeVisible({ timeout: 240_000 });
  await expect(page.getByRole("link", { name: "Protokoll GV.docx" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Budget 2026.xlsx" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Statuten.pdf" })).toBeVisible();
  await shoot(page, "04-drive-report");
});

test("Google Fotos: fehlende Zustimmung, Auswahl im neuen Fenster, Import", async ({ page, request }) => {
  test.setTimeout(300_000);
  await cancelOpenImports(request);
  await choose(page, /Google Fotos/);
  await expect(page.getByRole("heading", { name: "Mit Google Fotos verbinden" })).toBeVisible();

  // Häkchen für die Fotos beim Anbieter abgewählt → neu anmelden
  await page.getByRole("button", { name: "Bei Google Fotos anmelden" }).click();
  await signIn(page, "noscope");
  await expect(page.getByText(/nicht erlaubt\. Melde dich neu an/)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Neu anmelden" }).click();
  await signIn(page, "anna");
  await expect(page.getByText("Verbunden als anna@verein.test", { exact: true })).toBeVisible({ timeout: 30_000 });

  const popupPromise = page.context().waitForEvent("page");
  await page.getByRole("button", { name: "In Google Fotos auswählen" }).click();
  const popup = await popupPromise;
  await expect(page.getByText("Warte auf deine Auswahl in Google Fotos …").first()).toBeVisible();
  await shoot(page, "05-photos-waiting");
  await expect(popup.getByRole("heading", { name: "Google Fotos (Test)" })).toBeVisible({ timeout: 30_000 });
  expect(popup.url()).toMatch(/\/autoclose$/);
  await popup.getByRole("button", { name: "Fertig" }).click();
  await expect(popup.getByText("Auswahl übernommen.")).toBeVisible();
  await popup.close();

  // Der Wizard merkt das Ende der Auswahl selbst (Abfrage im Takt von Google)
  await expect
    .poll(async () => ((await (await request.get("/api/cloud-import/jobs")).json()) as { source: string; status: string }[])
      .filter((job) => job.source === "google_photos" && OPEN.includes(job.status)).map((job) => job.status).join(","), { timeout: 60_000 })
    .toMatch(/listing|ready/);
  const start = page.getByRole("button", { name: "Import starten" });
  await expect(start).toBeVisible({ timeout: 120_000 });
  await expect(start).toBeEnabled({ timeout: 30_000 });
  await start.click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Import starten" }).click();
  await expect(page.getByText(/Import abgeschlossen/)).toBeVisible({ timeout: 240_000 });
  await expect(page.getByRole("link", { name: "Google Fotos/IMG_2041.jpg" })).toBeVisible();
  await shoot(page, "06-photos-report");
});
