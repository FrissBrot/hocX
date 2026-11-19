import { test, expect, request as playwrightRequest, APIRequestContext, Page, TestInfo } from "@playwright/test";
import { authFiles } from "./auth";

// Seite «Kasse» nach Design «Kasse und Bussen v2» (1.4.1): Reiter «Bussen» mit Personen-Karten,
// Kassieren mit Rückgängig im Toast, Reiterwechsel zu «Konten» und Buchung inline erfassen.

test.use({ storageState: authFiles.admin });

const suffix = `${Date.now()}`;
const person = `E2E Kasse Person ${suffix}`;
const accountName = `E2E Kasse Konto ${suffix}`;
const txDescription = `E2E Getränke ${suffix}`;

async function json(api: APIRequestContext, method: "post" | "patch", path: string, data: unknown) {
  const response = await api[method](path, { data });
  expect(response.ok(), `${method.toUpperCase()} ${path}: ${await response.text()}`).toBeTruthy();
  return response.json();
}

/** Light/Dark bei 1440 und 390 px. */
async function screenshots(page: Page, testInfo: TestInfo, name: string) {
  await page.screenshot({ path: testInfo.outputPath(`${name}-1440.png`), fullPage: true });
  await page.evaluate(() => { document.documentElement.dataset.theme = "dark"; });
  await page.screenshot({ path: testInfo.outputPath(`${name}-1440-dark.png`), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: testInfo.outputPath(`${name}-390-dark.png`), fullPage: true });
  await page.evaluate(() => { document.documentElement.dataset.theme = "light"; });
  await page.screenshot({ path: testInfo.outputPath(`${name}-390.png`), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
}

test.describe("Kasse", () => {
  let api: APIRequestContext;
  let accountId = "";
  let participantId = "";
  let templateId = "";
  let protocolId = "";

  test.beforeAll(async () => {
    api = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.admin });
    accountId = (await json(api, "post", "/api/finance/accounts", { name: accountName, description: null })).id;
    participantId = (await json(api, "post", "/api/participants", { display_name: person, email: `e2e-kasse-${suffix}@example.invalid` })).id;
    const templates = await (await api.get("/api/templates")).json();
    const base = templates.find((item: { name: string }) => !item.name.startsWith("E2E")) ?? templates[0];
    templateId = (await json(api, "post", `/api/templates/${base.id}/duplicate`, { name: `E2E Kasse Vorlage ${suffix}` })).id;
    protocolId = (await json(api, "post", "/api/protocols/from-template", {
      template_id: templateId, protocol_date: new Date().toISOString().slice(0, 10), title: `E2E Kasse Protokoll ${suffix}`,
    })).id;
    for (const [fineType, amount] of [["late", 20], ["absent", 12]] as const) {
      await json(api, "post", "/api/fines", {
        protocol_id: protocolId, participant_id: participantId, participant_name_snapshot: person,
        fine_type: fineType, amount, account_id: accountId,
      });
    }
  });

  test.afterAll(async () => {
    // Buchungen und Bussen weg, damit sich das Konto löschen lässt
    const txs = await (await api.get(`/api/finance/accounts/${accountId}/transactions?limit=50`)).json().catch(() => []);
    for (const tx of Array.isArray(txs) ? txs : []) await api.delete(`/api/finance/transactions/${tx.id}`).catch(() => {});
    const fines = await (await api.get("/api/fines?limit=500")).json().catch(() => []);
    for (const fine of Array.isArray(fines) ? fines : []) {
      if (fine.participant_name_snapshot !== person) continue;
      if (fine.status === "collected") await api.post(`/api/fines/${fine.id}/reopen`).catch(() => {});
      await api.delete(`/api/fines/${fine.id}`).catch(() => {});
    }
    if (protocolId) await api.delete(`/api/protocols/${protocolId}`).catch(() => {});
    if (templateId) await api.delete(`/api/templates/${templateId}`).catch(() => {});
    if (participantId) await api.delete(`/api/participants/${participantId}`).catch(() => {});
    if (accountId) await api.delete(`/api/finance/accounts/${accountId}`).catch(() => {});
    await api.dispose();
  });

  test("Bussen kassieren mit Rückgängig, Reiterwechsel und Buchung hinzufügen", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/fines", { timeout: 30_000 });
    await expect(page.getByRole("heading", { level: 1, name: /Kasse/ })).toBeVisible();
    await expect(page.getByRole("tab", { name: /Bussen/ })).toHaveAttribute("aria-selected", "true");
    const card = page.getByRole("region", { name: person });
    await expect(card).toBeVisible();
    await expect(card.getByText("2 offen")).toBeVisible();
    await screenshots(page, testInfo, "kasse-bussen");

    // Liste-Ansicht
    await page.getByRole("tab", { name: "Liste" }).click();
    await expect(page.locator("table.kasse-table").getByText(person).first()).toBeVisible();
    await screenshots(page, testInfo, "kasse-bussen-liste");
    await page.getByRole("tab", { name: "Nach Person" }).click();

    // Alle kassieren → Toast mit Rückgängig
    await card.getByRole("button", { name: /Alle kassieren/ }).click();
    const toast = page.locator(".app-toast", { hasText: `${person}: CHF 32.00 kassiert` });
    await expect(toast).toBeVisible();
    await expect(page.getByRole("region", { name: person })).toHaveCount(0);
    await toast.getByRole("button", { name: "Rückgängig" }).click();
    await expect(page.getByRole("region", { name: person }).getByText("2 offen")).toBeVisible();
    expect((await (await api.get("/api/fines?limit=500")).json())
      .filter((fine: { participant_name_snapshot: string; status: string }) => fine.participant_name_snapshot === person)
      .every((fine: { status: string }) => fine.status === "pending")).toBeTruthy();

    // Reiterwechsel zu «Konten»
    await page.getByRole("tab", { name: "Konten" }).click();
    await expect(page).toHaveURL(/\/finances$/);
    await page.getByRole("button", { name: new RegExp(accountName) }).click();
    await expect(page.getByRole("heading", { level: 2, name: accountName })).toBeVisible();
    await expect(page.getByText(/aus offenen Bussen, noch nicht kassiert/)).toBeVisible();

    // Buchung inline erfassen
    await page.getByRole("button", { name: "+ Buchung" }).click();
    await page.getByRole("textbox", { name: /Betrag/ }).fill("15.50");
    await page.getByRole("textbox", { name: "Beschreibung" }).fill(txDescription);
    await page.getByRole("button", { name: "Hinzufügen" }).click();
    await expect(page.locator(".finance-tx-row", { hasText: txDescription })).toBeVisible();
    await expect(page.locator(".finance-tx-row", { hasText: txDescription })).toContainText("15.50");
    await screenshots(page, testInfo, "kasse-konten");
  });
});
