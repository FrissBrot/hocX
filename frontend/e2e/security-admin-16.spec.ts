import { randomBytes } from "node:crypto";
import { test, expect, request, type APIRequestContext, type Page } from "@playwright/test";
import { authFiles, platformAdminPasskeyFile } from "./auth";
import { SoftPasskey, stepUpHeaders } from "./soft-passkey";

// Sicherheitsbereich 1.6: Sperren-Dialog (manuell, Verlängern, Aufheben) und Ereignisfilter.
//
// Passkey-Bestätigung im Browser: die Oberfläche läuft echt (step-up/start, navigator.credentials,
// Anfrage mit Header). Der Browser hat aber keinen Schlüssel des Test-Admins - darum ersetzt die Route
// den Header der eigentlichen Anfrage durch eine echte Bestätigung des Software-Passkeys aus
// auth.setup.ts, gebunden an genau diese Methode, diesen Pfad und Body (wie admin-passkey.spec.ts).

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:13000";
const origin = new URL(baseURL).origin;

async function confirmStepUpsWithSoftPasskey(page: Page): Promise<{ api: APIRequestContext; passkey: SoftPasskey }> {
  const passkey = await SoftPasskey.load(platformAdminPasskeyFile);
  expect(passkey, "Software-Passkey aus auth.setup.ts fehlt").toBeTruthy();
  const api = await request.newContext({ baseURL, storageState: authFiles.platformAdmin, extraHTTPHeaders: { Origin: origin } });
  await page.addInitScript(() => {
    const one = new Uint8Array([1]).buffer;
    Object.defineProperty(navigator.credentials, "get", {
      configurable: true,
      value: async () => ({ id: "AQ", rawId: one, type: "public-key", response: { clientDataJSON: one, authenticatorData: one, signature: one, userHandle: null } }),
    });
  });
  await page.route("**/api/admin/mfa/step-up/start", (route) => route.fulfill({ json: { flow_token: "e2e", public_key: { challenge: "AQ", rpId: "localhost" } } }));
  await page.route(/\/api\/admin\/auth-security\/(blocks|events\/[^/?]+\/block)/, async (route) => {
    const original = route.request();
    if (original.method() === "GET") return route.continue();
    const url = new URL(original.url());
    const body = original.postData() ?? "";
    const confirm = await stepUpHeaders(api, passkey!, origin, "security-block", original.method(), url.pathname, body);
    const headers = Object.fromEntries(Object.entries(original.headers()).filter(([name]) => name.toLowerCase() !== "x-hocx-step-up"));
    await route.continue({ headers: { ...headers, ...confirm } });
  });
  return { api, passkey: passkey! };
}

test.describe("Sicherheitsbereich 1.6", () => {
  test.use({ storageState: authFiles.platformAdmin });
  test.setTimeout(240_000);

  test("Sperren: manuelle Sperre per Tastatur, Karte, Verlängern und Aufheben", async ({ page }) => {
    const { api, passkey } = await confirmStepUpsWithSoftPasskey(page);
    const reason = `E2E ${randomBytes(4).toString("hex")}`;
    const ip = `203.0.113.${10 + Math.floor(Math.random() * 200)}`;
    try {
      await page.goto("/admin/security/blocks");
      await expect(page.getByRole("heading", { name: "Abwehrstufen" })).toBeVisible();
      await page.getByRole("button", { name: "Manuelle Sperre" }).click();
      const dialog = page.getByRole("dialog", { name: "Manuelle Sperre" });
      const save = dialog.getByRole("button", { name: "Mit Passkey sperren" });
      await dialog.getByLabel("IP-Adresse").fill(ip);
      await expect(save).toBeDisabled();
      // Dauer per Tastatur: Pfeile in der Voreinstellungs-Leiste bis «Eigene»
      await dialog.getByRole("tab", { name: "1 h" }).focus();
      for (let index = 0; index < 5; index += 1) await page.keyboard.press("ArrowRight");
      await expect(dialog.getByRole("tab", { name: "Eigene" })).toHaveAttribute("aria-selected", "true");
      await dialog.getByLabel("Dauer in Minuten").fill("45");
      await dialog.getByLabel("Grund").fill(reason);
      await expect(save).toBeEnabled();
      await page.keyboard.press("Enter");
      await expect(page.getByText("Sperre gesetzt.")).toBeVisible();

      const listed = (await (await api.get("/api/admin/auth-security/blocks")).json()) as { short: string; reason: string; minutes: number }[];
      const block = listed.find((item) => item.reason === reason);
      expect(block?.minutes).toBe(45);
      const card = page.getByRole("article", { name: `Sperre ${block!.short}` });
      await expect(card).toBeVisible();
      await expect(card.getByText("Manuell")).toBeVisible();

      await card.getByRole("button", { name: "Verlängern" }).click();
      const extend = page.getByRole("dialog", { name: `Sperre ${block!.short} verlängern` });
      await extend.getByRole("tab", { name: "6 h" }).click();
      await extend.getByLabel("Grund").fill(`${reason} länger`);
      await extend.getByRole("button", { name: "Mit Passkey verlängern" }).click();
      await expect(page.getByText("Sperre verlängert.")).toBeVisible();
      const after = (await (await api.get("/api/admin/auth-security/blocks")).json()) as { short: string; minutes: number }[];
      expect(after.find((item) => item.short === block!.short)!.minutes).toBeGreaterThan(360);

      await card.getByRole("button", { name: "Aufheben" }).click();
      await page.getByRole("alertdialog").getByRole("button", { name: "Aufheben" }).click();
      await expect(page.getByText("Sperre aufgehoben.")).toBeVisible();
      await expect(card).toHaveCount(0);
      // Verlauf: Tabellenalternative zeigt die vorzeitig aufgehobene Sperre
      await page.getByRole("button", { name: "Daten als Tabelle" }).click();
      await expect(page.getByRole("row", { name: new RegExp(`${block!.short}.*vorzeitig aufgehoben`) }).first()).toBeVisible();
    } finally {
      await passkey.save(platformAdminPasskeyFile);
      await api.dispose();
    }
  });

  test("Ereignisse: Pseudonym-Filter, Token-Eingabe, Gruppen und Detail stehen in der URL", async ({ page }) => {
    // Ein paar Fehlversuche erzeugen (unbekannte Adressen, eigener Zeitraum 1 h)
    const anonymous = await request.newContext({ baseURL, extraHTTPHeaders: { Origin: origin } });
    for (let index = 0; index < 3; index += 1) {
      await anonymous.post("/api/auth/login", { data: { email: `e2e-${randomBytes(4).toString("hex")}@example.invalid`, password: "falsch-falsch" } });
    }
    await anonymous.dispose();

    await page.goto("/admin/security/events?range=1h&outcome=failure");
    await expect(page.getByRole("heading", { name: "Verlauf der gefilterten Ereignisse" })).toBeVisible();
    const firstPivot = page.getByRole("button", { name: /^Nach konto [0-9a-f]{12} filtern$/ }).first();
    await expect(firstPivot).toBeVisible();
    const subject = (await firstPivot.textContent())!.trim();
    await firstPivot.click();
    await expect(page).toHaveURL(new RegExp(`subject=${subject}`));
    await expect(page.getByRole("button", { name: `Filter konto: ${subject} entfernen` })).toBeVisible();

    // Token-Eingabe per Tastatur
    const input = page.getByLabel("Filter eingeben");
    await input.fill("land:ch");
    await input.press("Enter");
    await expect(page).toHaveURL(/country=CH/);
    await page.getByRole("button", { name: "Filter land: CH entfernen" }).click();
    await expect(page).not.toHaveURL(/country=/);
    await input.fill("person:timo");
    await input.press("Enter");
    await expect(page.getByText(/Unbekannter Filter/)).toBeVisible();

    // Gruppierung und zurück
    await page.getByRole("tab", { name: "Nach Netz" }).click();
    await expect(page).toHaveURL(/group=net/);
    await expect(page.getByRole("columnheader", { name: "Verteilung" })).toBeVisible();
    await page.getByRole("tab", { name: "Einzeln" }).click();

    // Detail: Zeit-Knopf öffnet das Ereignis (Tastatur), ID in der URL
    await page.getByRole("button", { name: /^Ereignis login\.password von/ }).first().focus();
    await page.keyboard.press("Enter");
    const drawer = page.locator("aside.admin-security-drawer");
    await expect(drawer.getByText(/Spur verfolgen/)).toBeVisible();
    await expect(page).toHaveURL(/event=[0-9a-f-]{36}/);
    await page.keyboard.press("Escape");
    // Keine Personendaten in der URL: nur Codes, Pseudonym-Präfixe und IDs
    expect(page.url()).not.toMatch(/@|example/);
  });
});
