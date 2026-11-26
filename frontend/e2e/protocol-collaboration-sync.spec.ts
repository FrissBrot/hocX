import { openProtocol } from "./protocol-page";
import { expect, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";

import { authFiles } from "./auth";

// Collaboration-Audit 1.6.1 (F-01, F-04): der letzte Stand kommt bei den anderen an, auch wenn der
// Block sofort verlassen wird, und schnelle eigene Änderungen an einer Aufzählung erzeugen keinen
// Konflikt mit sich selbst.

async function post(request: APIRequestContext, path: string, data: unknown) {
  const response = await request.post(path, { data });
  expect(response.ok(), `POST ${path}: ${await response.text()}`).toBeTruthy();
  return response.json();
}

type Block = { id: string; text_content: string | null; configuration_snapshot_json: Record<string, unknown> | null };

async function protocolWith(request: APIRequestContext, label: string, blocks: { title: string; type: number }[]) {
  const suffix = `${Date.now()}-${Math.round(Math.random() * 1e6)}`;
  const template = await post(request, "/api/templates", { name: `E2E Sync ${label} ${suffix}`, protocol_number_pattern: "Y-{n}", title_pattern: `${label} {dd.mm.yyyy}`, auto_create_next_protocol: false });
  const definition = await post(request, "/api/element-definitions", {
    title: "Diskussion",
    blocks: blocks.map((block, index) => ({ id: index + 1, title: block.title, element_type_id: block.type, render_type_id: 2, sort_index: (index + 1) * 10, configuration_json: {} })),
  });
  await post(request, `/api/templates/${template.id}/elements`, { element_definition_id: definition.id, sort_index: 10 });
  return post(request, "/api/protocols/from-template", { template_id: template.id, protocol_date: new Date().toISOString().slice(0, 10), title: `E2E Sync ${label} ${suffix}` });
}

async function serverBlocks(request: APIRequestContext, protocolId: string): Promise<Block[]> {
  const elements = (await (await request.get(`/api/protocols/${protocolId}/elements`)).json()) as { blocks: Block[] }[];
  return elements.flatMap((element) => element.blocks);
}

async function openAs(browser: Browser, storageState: string, protocolId: string, beforeOpen?: (page: Page) => void): Promise<Page> {
  const context = await browser.newContext({ storageState, viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  beforeOpen?.(page);
  await openProtocol(page, protocolId);
  return page;
}

/** Vom Server empfangene WS-Nachrichten eines Typs mitschreiben. */
function recordWsFrames(page: Page, type: string): string[] {
  const frames: string[] = [];
  page.on("websocket", (ws) => {
    ws.on("framereceived", (frame) => {
      const payload = typeof frame.payload === "string" ? frame.payload : "";
      if (payload.includes(`"type": "${type}"`) || payload.includes(`"type":"${type}"`)) frames.push(payload);
    });
  });
  return frames;
}

test("F-01: Text tippen und Block sofort mit Escape verlassen - die andere Person sieht den Text", async ({ browser }) => {
  test.setTimeout(120_000);
  const admin = (await browser.newContext({ storageState: authFiles.admin })).request;
  const protocol = await protocolWith(admin, "Escape", [{ title: "Notiz A", type: 1 }, { title: "Notiz B", type: 1 }]);

  let rejected: string[] = [];
  const adminPage = await openAs(browser, authFiles.admin, protocol.id, (page) => {
    rejected = recordWsFrames(page, "field_update_rejected");
  });
  const writerPage = await openAs(browser, authFiles.writer, protocol.id);
  const adminCards = adminPage.locator(".editor-block-card");
  const writerCards = writerPage.locator(".editor-block-card");
  await expect(adminCards.nth(0).locator(".editor-block-edit")).toHaveCount(1);
  await expect(writerCards.nth(0).locator(".editor-block-edit")).toHaveCount(1);

  await adminCards.nth(0).locator(".editor-block-edit").click();
  await expect(adminCards.nth(0).locator(".rich-text-editor-content")).toBeFocused();
  await expect(writerCards.nth(0)).toHaveClass(/editor-block-card-locked/);
  const saved = adminPage.waitForResponse((response) => response.url().endsWith("/text") && response.request().method() === "PUT");
  await adminPage.keyboard.type("Schlusssatz der Sitzung");
  // Wie eine Person, die nach dem letzten Wort sofort Escape drückt (vor der 700-ms-Entprellung)
  await adminPage.keyboard.press("Escape");
  expect((await saved).status()).toBe(200);

  // Ankunft beim anderen Client (Akzeptanz: ≤ 2 s nach dem Speichern; 3 s Spielraum für CI)
  await expect(writerCards.nth(0).locator(".markdown-view")).toContainText("Schlusssatz der Sitzung", { timeout: 3_000 });
  await expect(writerCards.nth(0)).not.toHaveClass(/editor-block-card-locked/);
  expect((await serverBlocks(admin, protocol.id))[0].text_content).toContain("Schlusssatz der Sitzung");
  expect(rejected, "kein field_update_rejected im normalen Ablauf").toEqual([]);

  // Folgeänderung durch die andere Person: keine 409 (Baseline ist aktuell)
  const writerSaved = writerPage.waitForResponse((response) => response.url().endsWith("/text") && response.request().method() === "PUT");
  await writerCards.nth(0).locator(".editor-block-edit").click();
  await expect(writerCards.nth(0).locator(".rich-text-editor-content")).toBeFocused();
  await writerPage.keyboard.press("End");
  await writerPage.keyboard.type(" Ergänzung");
  expect((await writerSaved).status()).toBe(200);

  await adminPage.context().close();
  await writerPage.context().close();
});

test("F-04: Aufzählungspunkt bearbeiten und sofort «+ Punkt» - beide Änderungen gespeichert, kein Konflikt", async ({ browser }) => {
  test.setTimeout(120_000);
  const admin = (await browser.newContext({ storageState: authFiles.admin })).request;
  const protocol = await protocolWith(admin, "Aufzaehlung", [{ title: "Stichworte", type: 8 }]);
  const page = await openAs(browser, authFiles.admin, protocol.id);
  const patchStatuses: number[] = [];
  page.on("response", (response) => {
    if (response.request().method() === "PATCH" && /\/api\/protocol-element-blocks\/[^/]+$/.test(response.url())) patchStatuses.push(response.status());
  });

  const card = page.locator('.editor-block-card[data-block-type="bullet_list"]');
  await card.getByRole("button", { name: /bearbeiten$/ }).click();
  await expect(card).toHaveClass(/editor-block-card-active/);
  const plus = card.getByRole("button", { name: "+ Punkt" });
  const first = page.waitForResponse((response) => response.request().method() === "PATCH" && response.url().includes("/api/protocol-element-blocks/"));
  await plus.click();
  expect((await first).status()).toBe(200);

  const item = card.locator("textarea.todo-input").first();
  await item.click();
  await item.pressSequentially("Budget 2027");
  // Blur speichert den Punkt, der Klick speichert den neuen leeren Punkt - direkt hintereinander
  await plus.click();

  await expect.poll(async () => (await serverBlocks(admin, protocol.id))[0].configuration_snapshot_json?.bullet_items, { timeout: 10_000 }).toEqual(["Budget 2027", ""]);
  await expect(card.locator("textarea.todo-input")).toHaveCount(2);
  await expect(card.locator("textarea.todo-input").first()).toHaveValue("Budget 2027");
  await page.waitForTimeout(500);
  expect(patchStatuses.filter((status) => status === 409), `PATCH-Status: ${patchStatuses.join(",")}`).toEqual([]);
  await expect(page.getByText(/von jemand anderem geändert/)).toHaveCount(0);

  await page.context().close();
});
