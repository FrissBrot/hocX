import { openProtocol } from "./protocol-page";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// Protokoll-Editor 1a (1.6): Blöcke statisch bis zur Aktivierung (Knopf, Klick, Strg+Enter,
// Escape), Gliederung mit Sortieren per Tastatur, Dock mit Schublade, Suche (Strg+F) und
// Statuswechsel mit Rückfrage. Screenshots unter test-results/editor-1a/.

const SHOTS = "test-results/editor-1a";

async function post(request: APIRequestContext, path: string, data: unknown) {
  const response = await request.post(path, { data });
  expect(response.ok(), `POST ${path}: ${await response.text()}`).toBeTruthy();
  return response.json();
}

type Element = { id: string; section_name_snapshot: string; blocks: { id: string; element_type_code: string }[] };

/** Protokoll mit drei Punkten: Begrüssung (Text), Pendenzen (Pendenzen), Varia (Text + Aufzählung). */
async function threePointProtocol(request: APIRequestContext, label: string) {
  const suffix = `${Date.now()}-${Math.round(Math.random() * 1e6)}`;
  const template = await post(request, "/api/templates", { name: `E2E 1a ${label} ${suffix}`, protocol_number_pattern: "A-{n}", title_pattern: `${label} {dd.mm.yyyy}`, auto_create_next_protocol: false });
  const points = [
    { title: "Begrüssung", blocks: [{ title: "Text", type: 1 }] },
    { title: "Pendenzen", blocks: [{ title: "Aufgaben", type: 2 }] },
    { title: "Varia", blocks: [{ title: "Notiz", type: 1 }, { title: "Stichworte", type: 8 }] },
  ];
  for (const [index, point] of points.entries()) {
    const definition = await post(request, "/api/element-definitions", {
      title: point.title,
      blocks: point.blocks.map((block, blockIndex) => ({ id: blockIndex + 1, title: block.title, block_title: block.title, element_type_id: block.type, render_type_id: 2, sort_index: (blockIndex + 1) * 10, configuration_json: {} })),
    });
    await post(request, `/api/templates/${template.id}/elements`, { element_definition_id: definition.id, sort_index: (index + 1) * 10 });
  }
  const protocol = await post(request, "/api/protocols/from-template", { template_id: template.id, protocol_date: new Date().toISOString().slice(0, 10), title: `E2E 1a ${label} ${suffix}` });
  const elements = (await (await request.get(`/api/protocols/${protocol.id}/elements`)).json()) as Element[];
  return { protocol, elements };
}

async function setTheme(page: Page, theme: "light" | "dark") {
  await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
  // Farbübergänge (--dur-base) abwarten, sonst zeigt der Screenshot Mischfarben
  await page.waitForTimeout(400);
}

test.describe("Protokoll-Editor 1a", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
  });

  test("Blöcke aktivieren: Knopf, Strg+Enter blockweise, Escape verlässt", async ({ request, page }) => {
    const { protocol } = await threePointProtocol(request, "Bloecke");
    await openProtocol(page, protocol.id);
    // Statisch: kein Editor im Dokument
    await expect(page.locator(".protocol-doc-section")).toHaveCount(3);
    await expect(page.locator(".rich-text-editor-content")).toHaveCount(0);

    const firstText = page.locator('.editor-block-card[data-block-type="text"]').first();
    await firstText.getByRole("button", { name: /bearbeiten$/ }).click();
    const editor = firstText.locator(".rich-text-editor-content");
    await expect(editor).toBeFocused();
    await page.keyboard.type("Begrüssung durch die Präsidentin");
    await page.screenshot({ path: `${SHOTS}/block-aktiv-light-1440.png` });

    // Strg+Enter: nächster Block (Pendenzen), dann weiter bis zum letzten - dort bleibt er
    await page.keyboard.press("ControlOrMeta+Enter");
    await expect(page.locator('.editor-block-card[data-block-type="todo"]')).toHaveClass(/editor-block-card-active/);
    await expect(page.locator(".rich-text-editor-content")).toHaveCount(0);
    await expect(firstText.locator(".markdown-view")).toContainText("Begrüssung durch die Präsidentin");
    await page.keyboard.press("ControlOrMeta+Enter");
    await page.keyboard.press("ControlOrMeta+Enter");
    const bullets = page.locator('.editor-block-card[data-block-type="bullet_list"]');
    await expect(bullets).toHaveClass(/editor-block-card-active/);
    await page.keyboard.press("ControlOrMeta+Enter");
    await expect(bullets).toHaveClass(/editor-block-card-active/);
    await expect(page).toHaveURL(new RegExp(`/protocols/${protocol.id}$`));
    // Rückwärts
    await page.keyboard.press("ControlOrMeta+Shift+Enter");
    await expect(page.locator('.editor-block-card[data-block-type="text"]').nth(1)).toHaveClass(/editor-block-card-active/);
    // Escape verlässt den Block, Fokus auf «Bearbeiten»
    await page.keyboard.press("Escape");
    await expect(page.locator(".editor-block-card-active")).toHaveCount(0);
    await expect(page.locator('.editor-block-card[data-block-type="text"]').nth(1).locator(".editor-block-edit")).toBeFocused();

    // Gespeichert
    await expect.poll(async () => {
      const elements = (await (await request.get(`/api/protocols/${protocol.id}/elements`)).json()) as { blocks: { text_content: string | null }[] }[];
      return elements.flatMap((element) => element.blocks).map((block) => block.text_content ?? "").join("|");
    }, { timeout: 15_000 }).toContain("Begrüssung durch die Präsidentin");
    await expect(page.locator(".protocol-save-state")).toContainText("Gespeichert");
  });

  test("Gliederung: Sprung zum Punkt und Sortieren per Tastatur", async ({ request, page }) => {
    const { protocol, elements } = await threePointProtocol(request, "Gliederung");
    await openProtocol(page, protocol.id);
    const outline = page.getByRole("navigation", { name: "Gliederung des Protokolls" });
    await expect(outline.getByRole("listitem")).toHaveCount(3);
    const variaItem = outline.locator(".protocol-outline-item", { hasText: "Varia" });
    await variaItem.click();
    await expect(variaItem).toHaveAttribute("aria-current", "location");
    await expect(page.locator(`#protocol-element-${elements[2].id}`)).toBeInViewport();

    // Alt+Pfeil verschiebt den fokussierten Punkt (Tastatur-Alternative zum Ziehen)
    await variaItem.focus();
    await page.keyboard.press("Alt+ArrowUp");
    await expect(outline.locator(".protocol-outline-title")).toHaveText(["Begrüssung", "Varia", "Pendenzen"]);
    await expect(page.locator(".protocol-doc-section-title")).toContainText(["Begrüssung", "Varia", "Pendenzen"]);
    await expect.poll(async () => {
      const fresh = (await (await request.get(`/api/protocols/${protocol.id}/elements`)).json()) as Element[];
      return fresh.map((element) => element.section_name_snapshot).join(",");
    }).toBe("Begrüssung,Varia,Pendenzen");
    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      await page.screenshot({ path: `${SHOTS}/gliederung-${theme}-1440.png` });
    }
  });

  test("Dock und Schublade: Kürzel, Escape, Status & Zusammenarbeit", async ({ request, page }) => {
    const { protocol } = await threePointProtocol(request, "Dock");
    await openProtocol(page, protocol.id);
    const drawer = page.locator("#protocol-drawer");
    await expect(drawer).toBeHidden();

    await page.locator('[data-drawer-button="notes"]').click();
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("heading", { name: "Sitzungsnotizen" })).toBeVisible();
    await expect(drawer.getByRole("textbox", { name: "Sitzungsnotizen" })).toBeFocused();
    await page.keyboard.type("Raum Dezember reservieren");
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(page.locator('[data-drawer-button="notes"]')).toBeFocused();

    await page.keyboard.press("Control+Alt+KeyS");
    await expect(drawer.getByRole("heading", { name: "Status & Zusammenarbeit" })).toBeVisible();
    await expect(drawer.getByText("Tastenkürzel")).toBeVisible();
    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      await page.screenshot({ path: `${SHOTS}/schublade-status-${theme}-1440.png` });
    }
    await setTheme(page, "light");
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();

    await page.locator('[data-drawer-button="agenda"]').click();
    await expect(drawer.getByRole("heading", { name: "Anliegen erfassen" })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/schublade-anliegen-light-1440.png` });
  });

  test("Suche: Strg+F öffnet die Protokollsuche und springt zum Treffer", async ({ request, page }) => {
    const { protocol, elements } = await threePointProtocol(request, "Suche");
    await openProtocol(page, protocol.id);
    await expect(page.locator(".protocol-doc-section")).toHaveCount(3);
    await page.keyboard.press("ControlOrMeta+f");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await page.keyboard.type("Varia");
    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      await page.screenshot({ path: `${SHOTS}/suche-${theme}-1440.png` });
    }
    await page.keyboard.press("Enter");
    await expect(dialog).toBeHidden();
    await expect(page.locator(`#protocol-element-${elements[2].id}`)).toBeInViewport();
  });

  test("Statuswechsel nur nach Rückfrage", async ({ request, page }) => {
    const { protocol } = await threePointProtocol(request, "Status");
    await openProtocol(page, protocol.id);
    await page.getByRole("button", { name: "Vorbereitung abschliessen" }).click();
    const dialog = page.getByRole("dialog", { name: "Vorbereitung abschliessen?" });
    await expect(dialog).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/statuswechsel-light-1440.png` });
    await dialog.getByRole("button", { name: "Abbrechen" }).click();
    await expect(dialog).toBeHidden();
    const unchanged = await (await request.get(`/api/protocols/${protocol.id}`)).json();
    expect(unchanged.status).toBe("geplant");

    await page.getByRole("button", { name: "Vorbereitung abschliessen" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Vorbereitung abschliessen" }).click();
    await expect.poll(async () => (await (await request.get(`/api/protocols/${protocol.id}`)).json()).status).toBe("vorbereitet");
  });

  test("Tablet: Gliederung als Überlagerung, Status-Varianten hell/dunkel", async ({ request, page }) => {
    const { protocol } = await threePointProtocol(request, "Tablet");
    await page.setViewportSize({ width: 1100, height: 820 });
    await openProtocol(page, protocol.id);
    const outlinePane = page.locator("#protocol-outline-pane");
    await expect(outlinePane).toBeHidden();
    await page.getByRole("button", { name: "Gliederung", exact: true }).click();
    await expect(outlinePane).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/tablet-gliederung-light-1100.png` });
    await page.keyboard.press("Escape");
    await expect(outlinePane).toBeHidden();

    // Status-Varianten (über die API, Screenshots für die Abnahme)
    for (const status of ["vorbereitet", "durchgeführt"]) {
      const response = await request.patch(`/api/protocols/${protocol.id}`, { data: { status } });
      expect(response.ok(), await response.text()).toBeTruthy();
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.reload();
      for (const theme of ["light", "dark"] as const) {
        await setTheme(page, theme);
        await page.screenshot({ path: `${SHOTS}/status-${status}-${theme}-1440.png` });
      }
    }
  });

  test("Traktanden: hinzufügen, umbenennen und beim Abschliessen in die Vorlage übernehmen", async ({ request, page }) => {
    test.setTimeout(120_000);
    const { protocol, elements } = await threePointProtocol(request, "Traktanden");
    await openProtocol(page, protocol.id);
    // Hinzufügen unter der Gliederung (nur in diesem Protokoll)
    const add = page.getByRole("textbox", { name: "Traktandum hinzufügen" });
    await add.fill("Neue Vereinsjacken");
    await add.press("Enter");
    await expect(page.locator(".protocol-doc-section-title", { hasText: "Neue Vereinsjacken" })).toBeVisible();
    await expect(page.locator(".editor-block-card-active .rich-text-editor-content")).toBeFocused();
    await page.keyboard.press("Escape");
    // Umbenennen über das Menü am Titel
    await page.getByRole("button", { name: "Aktionen für «Varia»" }).click();
    await page.getByRole("menuitem", { name: "Umbenennen" }).click();
    const title = page.getByRole("textbox", { name: "Titel des Traktandums" });
    await title.fill("Verschiedenes");
    await title.press("Enter");
    await expect(page.locator(".protocol-doc-section-title", { hasText: "Verschiedenes" })).toBeVisible();
    await expect(page.locator(`#protocol-element-${elements[2].id}`).getByText("umbenannt")).toBeVisible();

    // Bis «durchgeführt», dann abschliessen: Dialog listet die Abweichungen einzeln
    for (const status of ["vorbereitet", "durchgeführt"]) {
      const response = await request.patch(`/api/protocols/${protocol.id}`, { data: { status } });
      expect(response.ok(), await response.text()).toBeTruthy();
    }
    await openProtocol(page, protocol.id);
    await page.getByRole("button", { name: "Protokoll abschliessen" }).click();
    const dialog = page.getByRole("dialog", { name: "Protokoll abschliessen?" });
    await expect(dialog.getByText("Neu: «Neue Vereinsjacken» nach «Verschiedenes»")).toBeVisible();
    await expect(dialog.getByText("Umbenannt: «Varia» → «Verschiedenes»")).toBeVisible();
    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      await page.screenshot({ path: `${SHOTS}/vorlagen-dialog-${theme}-1440.png` });
    }
    await setTheme(page, "light");
    // Nur das Umbenennen übernehmen
    await dialog.getByRole("checkbox", { name: /Neue Vereinsjacken/ }).uncheck();
    await dialog.getByRole("button", { name: "Protokoll abschliessen" }).click();
    await expect.poll(async () => (await (await request.get(`/api/protocols/${protocol.id}`)).json()).status, { timeout: 30_000 }).toBe("abgeschlossen");
    const changes = await (await request.get(`/api/protocols/${protocol.id}/template-changes`)).json();
    expect(changes.changes.map((change: { kind: string }) => change.kind)).toEqual(["added"]);
  });
});
