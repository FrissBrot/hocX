import { test, expect, type APIRequestContext, type Page } from "@playwright/test";

import { authFiles } from "./auth";
import { shootCloud } from "./cloud-shots";

// Datei-Import aus Microsoft (P1) mit dem nachgebauten Anbieter des E2E-Stacks
// (CLOUD_IMPORT_FAKE_PROVIDERS, Backend services/cloud_import/fake_microsoft.py): Anmeldung mit
// Admin-Consent-Hinweis, Geschäftskonto, eigener Ordnerbaum per Tastatur, zweite Zustimmung für
// SharePoint, Auflisten im Hintergrund, Import, Bericht. Screenshots hell/dunkel bei 1440/390 px.
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
  await shootCloud(page, "cloud-ms", name);
}

async function signIn(page: Page, scenario: "work" | "personal" | "admin" | "cancel") {
  await expect(page.getByRole("heading", { name: /Test-Anmeldung/ })).toBeVisible();
  await page.locator(`button[data-scenario="${scenario}"]`).click();
  await page.waitForURL(/\/files\/import/);
}

test("Microsoft: anmelden, Ordner wählen, SharePoint nachfordern, importieren", async ({ page, request }) => {
  test.setTimeout(300_000);
  await cancelOpenImports(request);

  await page.goto("/files/import");
  await expect(page.getByRole("heading", { name: "Dateien importieren" })).toBeVisible();
  const tile = page.getByRole("radio", { name: /Microsoft OneDrive/ });
  await expect(tile).toBeVisible();
  await tile.click();
  await page.getByRole("button", { name: "Weiter", exact: true }).click();
  await expect(page.getByRole("heading", { name: /Mit Microsoft OneDrive \/ SharePoint verbinden/ })).toBeVisible();

  // 1. Organisation verlangt eine Freigabe durch die IT: Hinweis + Link für die IT
  await page.getByRole("button", { name: /Bei Microsoft OneDrive \/ SharePoint anmelden/ }).click();
  await signIn(page, "admin");
  await expect(page.getByText(/erst nach einer Freigabe durch ihre IT/)).toBeVisible();
  await page.getByLabel("Domain oder Tenant-ID der Organisation").fill("verein.onmicrosoft.com");
  const consent = page.getByRole("link", { name: "Freigabe-Link öffnen" });
  await expect(consent).toHaveAttribute("href", /login\.microsoftonline\.com\/verein\.onmicrosoft\.com\/adminconsent\?client_id=/);
  await shoot(page, "01-admin-consent");

  // 2. Geschäftskonto
  await page.getByRole("button", { name: /Bei Microsoft OneDrive \/ SharePoint anmelden/ }).click();
  await signIn(page, "work");
  await expect(page.getByText("Verbunden als anna@verein.test", { exact: true })).toBeVisible({ timeout: 30_000 });
  // Abschluss-Token nicht in der Adresszeile
  expect(page.url()).not.toContain("cloud_finish");

  // 3. Baum per Tastatur: «Mein OneDrive» aufklappen, Ordner «Fotos» wählen
  const expandMe = page.getByRole("button", { name: "Mein OneDrive aufklappen" });
  await expandMe.focus();
  await page.keyboard.press("Enter");
  const fotos = page.getByRole("checkbox", { name: "Fotos" });
  await expect(fotos).toBeVisible();
  await fotos.focus();
  await page.keyboard.press("Space");
  await expect(fotos).toBeChecked();
  await expect(page.getByText("1 Eintrag ausgewählt")).toBeVisible();
  await page.getByRole("button", { name: "Fotos aufklappen" }).click();
  await expect(page.getByRole("checkbox", { name: "Sommerlager 2025" })).toBeDisabled();
  await shoot(page, "02-tree");

  // 4. SharePoint braucht eine zweite Zustimmung (inkrementell)
  await page.getByRole("button", { name: "Zugriff erlauben" }).first().click();
  await signIn(page, "work");
  await expect(page.getByText("Verbunden als anna@verein.test", { exact: true })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Mein OneDrive aufklappen" }).click();
  await page.getByRole("checkbox", { name: "Fotos" }).check();
  await page.getByRole("button", { name: "SharePoint-Websites aufklappen" }).click();
  await page.getByRole("button", { name: "Vorstand aufklappen" }).click();
  // «Dokumente» gibt es zweimal (Ordner in OneDrive, Bibliothek der Website): die Bibliothek steht unten
  await page.getByRole("checkbox", { name: "Dokumente", exact: true }).last().check();
  await expect(page.getByText("2 Einträge ausgewählt")).toBeVisible();

  // 5. Auflisten im Hintergrund, dann Regeln/Vorschau wie bei ZIP
  await page.getByRole("button", { name: "Dateien auflisten" }).click();
  const start = page.getByRole("button", { name: "Import starten" });
  await expect(start).toBeVisible({ timeout: 120_000 });
  await expect(start).toBeEnabled({ timeout: 30_000 });
  await shoot(page, "03-rules");
  await start.click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Import starten" }).click();

  await expect(page.getByText(/Import abgeschlossen/)).toBeVisible({ timeout: 240_000 });
  await expect(page.getByRole("link", { name: "Dokumente/Sitzungen/Traktanden.pdf" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Fotos/Hock.jpg" })).toBeVisible();
  await shoot(page, "04-report");
});

test("Microsoft: Abbruch beim Anbieter und fremder Abschluss werden sauber gemeldet", async ({ page, request }) => {
  await cancelOpenImports(request);
  await page.goto("/files/import");
  await page.getByRole("radio", { name: /Microsoft OneDrive/ }).click();
  await page.getByRole("button", { name: "Weiter", exact: true }).click();
  await page.getByRole("button", { name: /Bei Microsoft OneDrive \/ SharePoint anmelden/ }).click();
  await signIn(page, "cancel");
  await expect(page.getByText("Die Anmeldung wurde abgebrochen.")).toBeVisible();
  // Ein erfundenes Abschluss-Token verbindet nichts
  // Erst wegnavigieren: nur ein geänderter Fragment-Teil wäre keine neue Seite (Effekt liefe nicht)
  await page.goto("about:blank");
  await page.goto("/files/import#cloud_finish=erfunden-erfunden-erfunden");
  await expect(page.getByText(/Die Anmeldung ist abgelaufen/)).toBeVisible();
  await cancelOpenImports(request);
});
