import { expect, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";

import { authFiles } from "./auth";

// Mitschreiben zu zweit (Performance-Audit 2026-11-22, K1): Sperren und Anwesenheit kommen nicht
// mehr über ein neues Editor-Objekt, sondern über ein Abonnement je Punkt. Verhalten unverändert:
// wer in einem Textblock tippt, sperrt ihn für die andere Person (Hinweis mit Namen, Feld nur
// lesbar), der andere Block bleibt frei, nach dem Verlassen ist er wieder frei, und der Text
// kommt bei der anderen Person an. Editor 1a: Blöcke sind statisch, bis sie aktiviert werden;
// erst der aktive Block sperrt.

async function post(request: APIRequestContext, path: string, data: unknown) {
  const response = await request.post(path, { data });
  expect(response.ok(), `POST ${path}: ${await response.text()}`).toBeTruthy();
  return response.json();
}

async function openAs(browser: Browser, storageState: string, protocolId: string): Promise<Page> {
  const context = await browser.newContext({ storageState, viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await page.goto(`/protocols/${protocolId}`);
  await expect(page.locator('.editor-block-card[data-block-type="text"] .editor-block-edit')).toHaveCount(2);
  return page;
}

test("Sperre eines Textblocks erscheint nur bei diesem Block und verschwindet nach dem Verlassen", async ({ browser }) => {
  test.setTimeout(120_000);
  const admin = await (await browser.newContext({ storageState: authFiles.admin })).request;
  const suffix = Date.now();
  const template = await post(admin, "/api/templates", { name: `E2E Sperren ${suffix}`, protocol_number_pattern: "S-{n}", title_pattern: "Sperren {dd.mm.yyyy}", auto_create_next_protocol: false });
  const definition = await post(admin, "/api/element-definitions", {
    title: "Diskussion",
    blocks: [
      { id: 1, title: "Notiz A", element_type_id: 1, render_type_id: 2, sort_index: 10, configuration_json: {} },
      { id: 2, title: "Notiz B", element_type_id: 1, render_type_id: 2, sort_index: 20, configuration_json: {} },
    ],
  });
  await post(admin, `/api/templates/${template.id}/elements`, { element_definition_id: definition.id, sort_index: 10 });
  const protocol = await post(admin, "/api/protocols/from-template", { template_id: template.id, protocol_date: new Date().toISOString().slice(0, 10), title: `E2E Sperren ${suffix}` });

  const adminPage = await openAs(browser, authFiles.admin, protocol.id);
  const writerPage = await openAs(browser, authFiles.writer, protocol.id);

  const writerCards = writerPage.locator(".editor-block-card");
  const adminCards = adminPage.locator(".editor-block-card");
  await adminCards.nth(0).getByRole("button", { name: /bearbeiten$/ }).click();
  const adminEditor = adminCards.nth(0).locator(".rich-text-editor-content");
  await expect(adminEditor).toBeFocused();
  // Gespeichert (und an die anderen verteilt) wird entprellt, solange die Sperre gilt
  const saved = adminPage.waitForResponse((response) => response.url().endsWith("/text") && response.request().method() === "PUT");
  await adminPage.keyboard.type("Hallo zusammen");
  await saved;

  // Gesperrt mit Namen, nur dieser Block: kein «Bearbeiten», der andere Block bleibt frei
  await expect(writerCards.nth(0)).toHaveClass(/editor-block-card-locked/);
  await expect(writerCards.nth(0).locator(".collab-lock-badge")).toBeVisible();
  await expect(writerCards.nth(0).locator(".editor-block-edit")).toHaveCount(0);
  await expect(writerCards.nth(1)).not.toHaveClass(/editor-block-card-locked/);
  await expect(writerCards.nth(1).locator(".editor-block-edit")).toHaveCount(1);

  // Die andere Richtung: Block B beim Schreibenden (per Tastatur), Admin sieht die Sperre nur dort
  await writerCards.nth(1).locator(".editor-block-edit").focus();
  await writerPage.keyboard.press("Enter");
  await expect(writerCards.nth(1).locator(".rich-text-editor-content")).toBeFocused();
  await expect(adminCards.nth(1)).toHaveClass(/editor-block-card-locked/);
  await expect(adminCards.nth(0)).not.toHaveClass(/editor-block-card-locked/);

  // Der Text ist bei der anderen Person angekommen (statische Anzeige)
  await expect(writerCards.nth(0).locator(".markdown-view")).toContainText("Hallo zusammen", { timeout: 15_000 });

  // Admin verlässt Block A mit Escape: beim Schreibenden wieder frei
  await adminPage.keyboard.press("Escape");
  await expect(adminCards.nth(0).locator(".rich-text-editor-content")).toHaveCount(0);
  await expect(writerCards.nth(0)).not.toHaveClass(/editor-block-card-locked/);
  await expect(writerCards.nth(0).locator(".editor-block-edit")).toHaveCount(1);

  await adminPage.context().close();
  await writerPage.context().close();
});
