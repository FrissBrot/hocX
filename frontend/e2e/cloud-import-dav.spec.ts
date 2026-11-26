import { test, expect, type APIRequestContext, type Page } from "@playwright/test";

import { authFiles } from "./auth";
import { shootCloud } from "./cloud-shots";

// Datei-Import aus WebDAV (kDrive, Nextcloud …) und Dropbox mit den nachgebauten Anbietern des
// E2E-Stacks (CLOUD_IMPORT_FAKE_PROVIDERS; Backend services/cloud_import/fake_webdav.py und
// fake_dropbox.py). WebDAV: falsches App-Passwort, gesperrte interne Adresse, Nextcloud-Vorlage,
// Ordnerbaum per Tastatur, Import. Dropbox: OAuth über die Test-Anmeldeseite, Ordner mit Paging,
// Import. Screenshots hell/dunkel bei 1440/390 px.
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
  await shootCloud(page, "cloud-dav", name);
}

async function chooseSource(page: Page, tile: RegExp) {
  await page.goto("/files/import");
  await expect(page.getByRole("heading", { name: "Dateien importieren" })).toBeVisible();
  // Dev-Server kompiliert beim ersten Aufruf nach und lädt dabei teils die Seite neu: erst danach klicken
  await page.waitForLoadState("networkidle");
  await page.getByRole("radio", { name: tile }).click();
  await page.getByRole("button", { name: "Weiter", exact: true }).click();
  await page.waitForLoadState("networkidle");
}

async function importSelection(page: Page) {
  await page.getByRole("button", { name: "Dateien auflisten" }).click();
  const start = page.getByRole("button", { name: "Import starten" });
  await expect(start).toBeVisible({ timeout: 120_000 });
  await expect(start).toBeEnabled({ timeout: 30_000 });
  await start.click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Import starten" }).click();
  await expect(page.getByText(/Import abgeschlossen/)).toBeVisible({ timeout: 240_000 });
}

test("WebDAV: App-Passwort, gesperrte Adresse, Nextcloud-Ordner per Tastatur importieren", async ({ page, request }) => {
  test.setTimeout(300_000);
  await cancelOpenImports(request);
  await chooseSource(page, /WebDAV \(kDrive, Nextcloud/);
  await expect(page.getByRole("heading", { name: /Mit WebDAV \(kDrive, Nextcloud …\) verbinden/ })).toBeVisible();
  await shoot(page, "01-webdav-form");

  // Interne Adresse: abgelehnt, bevor eine Verbindung aufgebaut wird
  await page.getByRole("combobox", { name: "Anbieter" }).selectOption("generic");
  await page.getByRole("textbox", { name: "WebDAV-Adresse" }).fill("https://169.254.169.254/latest/");
  await page.getByLabel("Benutzername").fill("anna");
  await page.getByLabel("App-Passwort").fill("app-passwort-e2e");
  await page.getByRole("button", { name: "Verbinden" }).click();
  await expect(page.getByText(/Diese Adresse ist nicht erlaubt/)).toBeVisible();

  // Nextcloud-Vorlage mit falschem Passwort, dann richtig (per Tastatur absenden)
  await page.getByRole("combobox", { name: "Anbieter" }).selectOption("nextcloud");
  await page.getByLabel("Serveradresse").fill("cloud.verein.example");
  await page.getByLabel("App-Passwort").fill("wrong-passwort");
  await page.getByRole("button", { name: "Verbinden" }).click();
  await expect(page.getByText("Benutzername oder App-Passwort stimmen nicht.")).toBeVisible();
  await shoot(page, "02-webdav-error");
  await page.getByLabel("App-Passwort").fill("app-passwort-e2e");
  await page.getByLabel("App-Passwort").press("Enter");
  await expect(page.getByText("Verbunden als anna @ cloud.verein.example", { exact: true })).toBeVisible({ timeout: 30_000 });
  // Passwort nie im Seiteninhalt
  expect(await page.content()).not.toContain("app-passwort-e2e");

  const expandRoot = page.getByRole("button", { name: "Alle Dateien aufklappen" });
  await expandRoot.focus();
  await page.keyboard.press("Enter");
  const fotos = page.getByRole("checkbox", { name: "Fotos" });
  await expect(fotos).toBeVisible();
  await fotos.focus();
  await page.keyboard.press("Space");
  await expect(fotos).toBeChecked();
  await page.getByRole("checkbox", { name: "Protokolle" }).check();
  await expect(page.getByText("2 Einträge ausgewählt")).toBeVisible();
  await shoot(page, "03-webdav-tree");

  await importSelection(page);
  await expect(page.getByRole("link", { name: "Protokolle/GV 2024.pdf" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Fotos/2024/Hock.png" })).toBeVisible();
  await shoot(page, "04-webdav-report");
});

test("Dropbox: anmelden, Ordner mit mehreren Seiten wählen, importieren", async ({ page, request }) => {
  test.setTimeout(300_000);
  await cancelOpenImports(request);
  await chooseSource(page, /^Dropbox/);
  await expect(page.getByRole("heading", { name: "Mit Dropbox verbinden" })).toBeVisible();
  await shoot(page, "05-dropbox-connect");

  // Abbruch auf der Anmeldeseite
  await page.getByRole("button", { name: "Bei Dropbox anmelden" }).click();
  await expect(page.getByRole("heading", { name: /Test-Anmeldung/ })).toBeVisible();
  await page.locator('button[data-scenario="cancel"]').click();
  await page.waitForURL(/\/files\/import/);
  await expect(page.getByText("Die Anmeldung wurde abgebrochen.")).toBeVisible();

  await page.getByRole("button", { name: "Bei Dropbox anmelden" }).click();
  await page.locator('button[data-scenario="anna"]').click();
  await page.waitForURL(/\/files\/import/);
  await expect(page.getByText("Verbunden als anna@verein.test", { exact: true })).toBeVisible({ timeout: 30_000 });
  expect(page.url()).not.toContain("cloud_finish");

  await page.getByRole("button", { name: "Dropbox aufklappen" }).click();
  await page.getByRole("button", { name: "Fotos aufklappen" }).click();
  await page.getByRole("button", { name: "Sommerlager aufklappen" }).click();
  // Zweite Seite über den Cursor (files/list_folder/continue)
  await page.getByRole("button", { name: "Weitere laden" }).click();
  await expect(page.getByText("See.jpg")).toBeVisible();
  await page.getByRole("checkbox", { name: "Fotos" }).check();
  await page.getByRole("checkbox", { name: "Statuten.pdf" }).check();
  await shoot(page, "06-dropbox-tree");

  await importSelection(page);
  await expect(page.getByRole("link", { name: "Statuten.pdf" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Fotos/Sommerlager/See.jpg" })).toBeVisible();
  await shoot(page, "07-dropbox-report");
});
