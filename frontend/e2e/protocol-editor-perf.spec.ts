import fs from "node:fs";
import path from "node:path";

import { openProtocol } from "./protocol-page";
import { expect, test, type APIRequestContext } from "@playwright/test";

// Performance-Quick-Wins im Protokoll-Editor (1.5.1, Audit perf-protocol-editor 2026-11-22):
// Bilderraster lädt Vorschauen statt Originale (Vollbild bleibt Original), Entwürfe überstehen
// sofortiges Neuladen trotz gebündeltem Speichern, Statistik-Diagramme laden einmal statt doppelt.
// Editor 1a (1.6): Text ist statisch, bis der Block aktiviert wird (L4); Diagramme erst beim
// Hinscrollen (L2).

async function json(request: APIRequestContext, urlPath: string, data: unknown) {
  const response = await request.post(urlPath, { data });
  expect(response.ok(), `POST ${urlPath}: ${await response.text()}`).toBeTruthy();
  return response.json();
}

type Block = { id: string; element_type_code: string };

async function protocolWith(request: APIRequestContext, label: string, blocks: { type: number; title: string; config?: Record<string, unknown> }[]) {
  const suffix = `${Date.now()}-${Math.round(Math.random() * 1e6)}`;
  const template = await json(request, "/api/templates", { name: `E2E ${label} ${suffix}`, protocol_number_pattern: "P-{n}", title_pattern: `${label} {dd.mm.yyyy}`, auto_create_next_protocol: false });
  const definition = await json(request, "/api/element-definitions", {
    title: `${label} ${suffix}`,
    blocks: blocks.map((block, index) => ({ id: index + 1, title: block.title, block_title: block.title, element_type_id: block.type, render_type_id: 2, sort_index: (index + 1) * 10, configuration_json: block.config ?? {} })),
  });
  await json(request, `/api/templates/${template.id}/elements`, { element_definition_id: definition.id, sort_index: 10 });
  const protocol = await json(request, "/api/protocols/from-template", { template_id: template.id, protocol_date: new Date().toISOString().slice(0, 10), title: `E2E ${label} ${suffix}` });
  const elements = (await (await request.get(`/api/protocols/${protocol.id}/elements`)).json()) as { blocks: Block[] }[];
  return { protocol, blocks: elements.flatMap((element) => element.blocks) };
}

test("Bilderraster zeigt die Vorschau, das Vollbild das Original", async ({ request, page }) => {
  const { protocol, blocks } = await protocolWith(request, "Bilder", [{ type: 3, title: "Bilder" }]);
  const imageBlock = blocks.find((block) => block.element_type_code === "image")!;
  const png = fs.readFileSync(path.join(__dirname, "fixtures/photos/sample.png"));
  const upload = await request.post(`/api/protocol-element-blocks/${imageBlock.id}/images`, {
    multipart: { file: { name: "vorschau.png", mimeType: "image/png", buffer: png }, title: "Vorschau" },
  });
  expect(upload.ok(), await upload.text()).toBeTruthy();

  await openProtocol(page, protocol.id);
  const tile = page.locator(".image-grid img.image-lightbox-trigger").first();
  await expect(tile).toBeVisible();
  await expect(tile).toHaveAttribute("src", /\/api\/stored-files\/[^/]+\/thumbnail$/);
  // Die Vorschau lädt tatsächlich (gleiche Berechtigung wie das Original)
  await expect.poll(() => tile.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);

  await tile.click();
  const full = page.locator(".image-lightbox-img");
  await expect(full).toHaveAttribute("src", /\/api\/stored-files\/[^/]+\/content$/);
  await page.keyboard.press("Escape");
});

test("Entwurf übersteht sofortiges Neuladen trotz gebündeltem Speichern", async ({ request, page }) => {
  const { protocol } = await protocolWith(request, "Entwurf", [{ type: 1, title: "Text" }]);
  await openProtocol(page, protocol.id);
  // Statisch, bis der Block aktiviert wird: dann erst lädt Tiptap
  await expect(page.locator(".rich-text-editor-content")).toHaveCount(0);
  await page.getByRole("button", { name: /bearbeiten$/ }).first().click();
  const editor = page.locator(".editor-block-card-active .rich-text-editor-content").first();
  await expect(editor).toBeFocused();
  const text = `Sofort neu geladen ${Date.now()}`;
  await page.keyboard.type(text, { delay: 0 });

  // Verlassen des Tabs schreibt den gepufferten Entwurf sofort nach localStorage
  const drafts = await page.evaluate(() => {
    window.dispatchEvent(new Event("pagehide"));
    return Object.keys(localStorage).filter((key) => key.startsWith("hocx-draft-v1:")).map((key) => localStorage.getItem(key) ?? "");
  });
  expect(drafts.some((draft) => draft.includes(text))).toBe(true);

  // Neuladen ohne Warten: nichts geht verloren - die gepufferte Änderung erreicht den Server
  // (Outbox wird beim Laden gesendet). Hinweis: zeigt der Editor danach noch den alten
  // Serverstand, liegt das an einem bestehenden Ablauf (Outbox-Versand vor dem Mount des Editors
  // löscht den Entwurf), nicht am Puffer - geprüft wird darum der Serverstand.
  await page.reload();
  await expect
    .poll(async () => {
      const elements = (await (await request.get(`/api/protocols/${protocol.id}/elements`)).json()) as { blocks: { text_content: string | null }[] }[];
      return elements.flatMap((element) => element.blocks).map((block) => block.text_content ?? "").join("\n");
    }, { timeout: 15_000 })
    .toContain(text);
  await page.reload();
  await expect(page.locator('.editor-block-card[data-block-type="text"] .markdown-view').first()).toContainText(text);
});

test("Statistik-Diagramm lädt beim Öffnen genau einmal", async ({ request, page }) => {
  const { protocol } = await protocolWith(request, "Statistik", [{ type: 15, title: "Statistik", config: { chart_type: "todos" } }]);
  const statsRequests: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/statistics/overview")) statsRequests.push(req.url());
  });
  await openProtocol(page, protocol.id);
  // Recharts wird nachgeladen und zeichnet
  await expect(page.locator(".protocol-doc-section .recharts-wrapper").first()).toBeVisible();
  await page.waitForTimeout(2000);
  expect(statsRequests, statsRequests.join("\n")).toHaveLength(1);
});
