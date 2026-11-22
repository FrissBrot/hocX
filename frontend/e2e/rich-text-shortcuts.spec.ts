import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// Tastenkürzel und Markdown-Eingaberegeln im Text-Element des Protokoll-Editors
// (rich-text-editor.tsx): Strg/⌘+B/I, Listen (Strg+Shift+8/7), «**fett**», «*kursiv*», «- »/«1. »,
// Rückgängig/Wiederholen. Geprüft wird das gespeicherte Markdown (PUT .../text) und dass die Toolbar
// den Formatstatus sofort zeigt (aria-pressed) sowie die Kürzel im Tooltip nennt.

async function post(request: APIRequestContext, path: string, data: unknown) {
  const response = await request.post(path, { data });
  expect(response.ok(), `POST ${path}: ${await response.text()}`).toBeTruthy();
  return response.json();
}

test.describe("Rich-Text-Tastenkürzel im Protokoll", () => {
  let protocolId: string | null = null;

  test.afterAll(async ({ request }) => {
    if (protocolId) await request.delete(`/api/protocols/${protocolId}`).catch(() => {});
  });

  test("Kürzel und Eingaberegeln formatieren den Text", async ({ request, page }) => {
    test.setTimeout(180_000);
    const suffix = Date.now();
    const template = await post(request, "/api/templates", { name: `E2E Kürzel ${suffix}`, protocol_number_pattern: "K-{n}", title_pattern: "Kürzel {dd.mm.yyyy}", auto_create_next_protocol: false });
    const definition = await post(request, "/api/element-definitions", {
      title: "Notizen",
      blocks: [{ id: 1, title: "Text", element_type_id: 1, render_type_id: 2, sort_index: 10, configuration_json: {} }],
    });
    await post(request, `/api/templates/${template.id}/elements`, { element_definition_id: definition.id, sort_index: 10 });
    const protocol = await post(request, "/api/protocols/from-template", { template_id: template.id, protocol_date: new Date().toISOString().slice(0, 10), title: `E2E Kürzel ${suffix}` });
    protocolId = protocol.id;

    // Zuletzt gespeichertes Markdown (Speichern ist entprellt)
    let saved = "";
    page.on("request", (req) => {
      if (req.method() === "PUT" && /\/api\/protocol-element-blocks\/[^/]+\/text$/.test(req.url())) {
        saved = (JSON.parse(req.postData() ?? "{}") as { content?: string }).content ?? "";
      }
    });

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/protocols/${protocol.id}`);
    const editor = page.locator(".tracked-text-block .rich-text-editor-content").first();
    await expect(editor).toBeVisible();
    await expect(editor).toHaveAttribute("contenteditable", "true");

    // Tooltips nennen die Tasten der Plattform (Linux-Chromium: Strg)
    const toolbar = page.locator(".tracked-text-block .rich-text-toolbar").first();
    await expect(toolbar.getByRole("button", { name: "B", exact: true })).toHaveAttribute("title", "Fett (Strg+B)");
    await expect(toolbar.getByRole("button", { name: "I", exact: true })).toHaveAttribute("title", "Kursiv (Strg+I)");
    await expect(toolbar.getByRole("button", { name: "Aufzählung" })).toHaveAttribute("title", "Aufzählung (Strg+Umschalt+8)");
    await expect(toolbar.getByRole("button", { name: "Nummerierte Liste" })).toHaveAttribute("title", "Nummerierte Liste (Strg+Umschalt+7)");
    const boldButton = toolbar.getByRole("button", { name: "B", exact: true });

    await editor.click();
    await expect(editor).toBeFocused();

    async function reset(p: Page) {
      await p.keyboard.press("ControlOrMeta+a");
      await p.keyboard.press("Backspace");
    }
    async function expectSaved(markdown: string, label: string) {
      await expect.poll(() => saved.trim(), { message: label, timeout: 10_000 }).toBe(markdown);
    }

    // Strg+B / Strg+I auf markiertem Wort
    await page.keyboard.type("Hallo Welt");
    for (let i = 0; i < 4; i += 1) await page.keyboard.press("Shift+ArrowLeft");
    // ProseMirror übernimmt die Browser-Auswahl erst mit «selectionchange»
    await expect.poll(() => page.evaluate(() => document.getSelection()?.toString())).toBe("Welt");
    await page.waitForTimeout(100);
    await page.keyboard.press("ControlOrMeta+b");
    await expectSaved("Hallo **Welt**", "Strg+B");
    await page.keyboard.press("ControlOrMeta+b");
    await page.keyboard.press("ControlOrMeta+i");
    await expectSaved("Hallo *Welt*", "Strg+I");

    // Strg+B ohne Auswahl schaltet für das Weitertippen um - die Toolbar zeigt es sofort an
    // (Tiptap v3 rendert ohne useEditorState nicht neu: «B» blieb unmarkiert)
    await reset(page);
    await page.keyboard.type("A ");
    await expect(boldButton).toHaveAttribute("aria-pressed", "false");
    await page.keyboard.press("ControlOrMeta+b");
    await expect(boldButton).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.type("fett");
    await page.keyboard.press("ControlOrMeta+b");
    await expect(boldButton).toHaveAttribute("aria-pressed", "false");
    await page.keyboard.type(" B");
    await expectSaved("A **fett** B", "Strg+B beim Tippen");
    // Cursor in fetten Text: «B» aktiv, wieder hinaus: inaktiv
    for (let i = 0; i < 4; i += 1) await page.keyboard.press("ArrowLeft");
    await expect(boldButton).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("End");
    await expect(boldButton).toHaveAttribute("aria-pressed", "false");
    // Klick auf «B» ohne Auswahl wirkt ebenso sichtbar
    await reset(page);
    await boldButton.click();
    await expect(boldButton).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.type("fett");
    await boldButton.click();
    await expect(boldButton).toHaveAttribute("aria-pressed", "false");
    await page.keyboard.type(" normal");
    await expectSaved("**fett** normal", "Klick auf B");

    // Markdown-Eingaberegeln
    await reset(page);
    await page.keyboard.type("x **fett** und *kursiv* y");
    await expectSaved("x **fett** und *kursiv* y", "**fett** / *kursiv*");
    await expect(editor.locator("strong")).toHaveText("fett");
    await expect(editor.locator("em")).toHaveText("kursiv");

    await reset(page);
    await page.keyboard.type("- eins");
    await expect(editor.locator("ul li")).toHaveText("eins");
    await expectSaved("- eins", "«- » am Zeilenanfang");

    await reset(page);
    await reset(page);
    await page.keyboard.type("1. eins");
    await expect(editor.locator("ol li")).toHaveText("eins");
    await expectSaved("1. eins", "«1. » am Zeilenanfang");

    // Listen-Kürzel
    await reset(page);
    await reset(page);
    await page.keyboard.type("zwei");
    await page.keyboard.press("ControlOrMeta+Shift+8");
    await expect(editor.locator("ul li")).toHaveText("zwei");
    await expectSaved("- zwei", "Strg+Shift+8");
    await page.keyboard.press("ControlOrMeta+Shift+8");
    await page.keyboard.press("ControlOrMeta+Shift+7");
    await expect(editor.locator("ol li")).toHaveText("zwei");
    await expectSaved("1. zwei", "Strg+Shift+7");

    // Rückgängig / Wiederholen
    await reset(page);
    await reset(page);
    await page.keyboard.type("Basis");
    await expectSaved("Basis", "Basis");
    await page.waitForTimeout(600); // eigener Undo-Schritt
    await page.keyboard.type(" Zusatz");
    await expectSaved("Basis Zusatz", "Zusatz");
    await page.keyboard.press("ControlOrMeta+z");
    await expectSaved("Basis", "Strg+Z");
    await page.keyboard.press("ControlOrMeta+Shift+z");
    await expectSaved("Basis Zusatz", "Strg+Shift+Z");
    await page.keyboard.press("ControlOrMeta+z");
    await expectSaved("Basis", "Strg+Z (2)");
    await page.keyboard.press("ControlOrMeta+y");
    await expectSaved("Basis Zusatz", "Strg+Y");
  });
});
