import { test, expect, type APIRequestContext, type Page } from "@playwright/test";

// Bausteinliste (/elements): Platzhalter-Pillen, Inhalt-Chips, «Verwendet»-Spalte, Suche ohne
// Treffer und Zeilenmenü. Legt Screenshots (Light/Dark, 1440 px) ab. Auf dem Handy (≤ 900 px)
// zeigt /elements nur den Hinweis, den Bereich am Computer zu öffnen - davon ebenfalls Screenshots.

const stamp = Date.now();

function block(id: number, elementTypeId: number, title: string, blockTitle: string | null = null) {
  return { id, title, block_title: blockTitle, element_type_id: elementTypeId, render_type_id: 2, sort_index: id * 10, configuration_json: {} };
}

async function createDefinition(request: APIRequestContext, title: string, blocks: ReturnType<typeof block>[]) {
  const response = await request.post("/api/element-definitions", { data: { title, blocks } });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()) as { id: string; title: string };
}

async function setTheme(page: Page, theme: string) {
  await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
  await page.reload();
}

test("Bausteinliste: Pillen, Chips, Verwendung, Suche und Menü", async ({ page, request }) => {
  test.setTimeout(240_000);
  const shotDir = process.env.E2E_SHOT_DIR ?? "test-results";
  const prefix = `E2E Liste ${stamp}`;
  const program = await createDefinition(request, `${prefix} Jahresprogramm {cycle_year_start}`, [
    block(1, 1, "Einleitung"),
    block(2, 7, "Termine"),
    block(3, 1, "Schluss"),
  ]);
  const tasks = await createDefinition(request, `${prefix} Pendenzen`, [block(1, 2, "Offene Pendenzen"), block(2, 1, "Notiz")]);
  const single = await createDefinition(request, `${prefix} Begrüssung`, [block(1, 1, "Begrüssung {cycle_name}", "Willkommen")]);
  const template = await (await request.post("/api/templates", { data: { name: `${prefix} Vorlage` } })).json();
  const templateElement = await request.post(`/api/templates/${template.id}/elements`, {
    data: { element_definition_id: tasks.id, sort_index: 10, configuration_json: {} },
  });
  expect(templateElement.ok(), await templateElement.text()).toBeTruthy();

  try {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/elements");
    const search = page.getByPlaceholder("Bausteine durchsuchen");

    // Platzhalter als Pille, Inhalt als Chips in Blockreihenfolge, Verwendung
    const programRow = page.getByRole("row", { name: new RegExp(`${prefix} Jahresprogramm`) });
    await expect(programRow.locator("code.element-library-placeholder")).toHaveText("{cycle_year_start}");
    await expect(programRow.locator("code.element-library-placeholder")).toHaveAttribute("title", "Wird beim Einfügen ersetzt");
    await expect(programRow.locator(".badge")).toHaveText(["Text", "Terminliste"]);
    await expect(programRow.getByRole("cell", { name: "—", exact: true })).toBeVisible();
    await expect(programRow).toContainText("Heute geändert");
    const tasksRow = page.getByRole("row", { name: new RegExp(`${prefix} Pendenzen`) });
    await expect(tasksRow.getByRole("cell", { name: "1 Vorlage", exact: true })).toBeVisible();

    // Suche: Zähler folgt den Treffern
    await search.fill(prefix);
    await expect(page.getByText("3 Bausteine", { exact: true })).toBeVisible();

    for (const theme of ["light", "dark"]) {
      await setTheme(page, theme);
      await page.getByPlaceholder("Bausteine durchsuchen").fill(prefix);
      await expect(page.getByText("3 Bausteine", { exact: true })).toBeVisible();
      await page.locator("section.panel").first().screenshot({ path: `${shotDir}/elements-list-${theme}-1440.png` });

      await page.getByPlaceholder("Bausteine durchsuchen").fill(`${prefix} gibt es nicht`);
      await expect(page.getByText("Keine Bausteine gefunden.")).toBeVisible();
      await expect(page.getByText("0 Bausteine", { exact: true })).toBeVisible();
      await page.locator("section.panel").first().screenshot({ path: `${shotDir}/elements-list-empty-${theme}-1440.png` });

      await page.getByPlaceholder("Bausteine durchsuchen").fill(prefix);
      await page.getByRole("button", { name: `Aktionen für «${program.title}»` }).click();
      const menu = page.getByRole("menu");
      await expect(menu.getByRole("menuitem")).toHaveText(["Bearbeiten", "Duplizieren", "Löschen"]);
      await expect(menu.getByRole("separator")).toHaveCount(1);
      await page.screenshot({ path: `${shotDir}/elements-list-menu-${theme}-1440.png` });
      await page.keyboard.press("Escape");
      await expect(menu).toBeHidden();
    }

    await setTheme(page, "light");
    await page.getByPlaceholder("Bausteine durchsuchen").fill(prefix);

    // Ganze Zeile klickbar = Bearbeiten
    await tasksRow.getByRole("cell").nth(1).click();
    const editDialog = page.getByRole("dialog", { name: `Element bearbeiten: ${tasks.title}` });
    await expect(editDialog).toBeVisible();
    await editDialog.press("Escape");
    await expect(editDialog).toBeHidden();

    // Tastatur: Enter auf dem Namen öffnet ebenfalls
    await tasksRow.getByRole("button", { name: tasks.title, exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(editDialog).toBeVisible();
    await editDialog.press("Escape");

    // Löschen fragt mit Namen nach; Abbrechen lässt den Baustein stehen
    await page.getByRole("button", { name: `Aktionen für «${program.title}»` }).click();
    await page.getByRole("menuitem", { name: "Löschen" }).click();
    const confirmDialog = page.getByRole("alertdialog").filter({ hasText: `Baustein «${program.title}» löschen?` });
    await expect(confirmDialog).toBeVisible();
    await confirmDialog.getByRole("button", { name: "Abbrechen" }).click();
    await expect(programRow).toBeVisible();

    // Dialog «Baustein bearbeiten»: mehrere Blöcke, ein Block, Löschbestätigung offen
    for (const theme of ["light", "dark"]) {
      await setTheme(page, theme);
      await page.getByPlaceholder("Bausteine durchsuchen").fill(prefix);
      await programRow.locator(".element-library-name").click();
      const dialog = page.getByRole("dialog", { name: `Element bearbeiten: ${program.title}` });
      await expect(dialog.locator(".element-definition-block")).toHaveCount(3);
      await expect(dialog.getByText("3 Blöcke · Klick öffnet, Ziehen sortiert")).toBeVisible();
      await page.screenshot({ path: `${shotDir}/element-dialog-${theme}-1440.png` });
      await dialog.getByRole("button", { name: "Block löschen" }).nth(1).click();
      await expect(dialog.getByText("Block löschen?")).toBeVisible();
      await page.screenshot({ path: `${shotDir}/element-dialog-confirm-${theme}-1440.png` });
      await dialog.getByRole("button", { name: "Nein" }).click();
      await dialog.getByRole("button", { name: "Abbrechen" }).click();
      await expect(dialog).toBeHidden();

      await page.getByRole("button", { name: single.title, exact: true }).click();
      const singleDialog = page.getByRole("dialog", { name: `Element bearbeiten: ${single.title}` });
      await expect(singleDialog.getByText("1 Block · Klick öffnet, Ziehen sortiert")).toBeVisible();
      await expect(singleDialog.getByText("Überschrift: Willkommen")).toBeVisible();
      await page.screenshot({ path: `${shotDir}/element-dialog-single-${theme}-1440.png` });
      await singleDialog.getByRole("button", { name: "Abbrechen" }).click();
      await expect(singleDialog).toBeHidden();
    }

    // Platzhalter einfügen und per Alt+Pfeil sortieren (speichert sofort)
    await setTheme(page, "light");
    await page.getByPlaceholder("Bausteine durchsuchen").fill(prefix);
    await programRow.locator(".element-library-name").click();
    const dialog = page.getByRole("dialog", { name: `Element bearbeiten: ${program.title}` });
    const titleInput = dialog.getByRole("textbox", { name: "Elementtitel" });
    await titleInput.focus();
    await titleInput.press("End");
    await dialog.getByRole("button", { name: "{cycle_year_end}" }).click();
    await expect(titleInput).toHaveValue(`${program.title} {cycle_year_end}`);
    await expect(titleInput).toBeFocused();
    await dialog.locator(".element-definition-block-main").first().press("Alt+ArrowDown");
    await expect(dialog.locator(".element-definition-block-main").first()).toContainText("Termine");
    await dialog.getByRole("button", { name: "Abbrechen" }).click();

    // Handy: Hinweis auf den Computer (MobileDesktopOnly)
    for (const theme of ["light", "dark"]) {
      await page.setViewportSize({ width: 390, height: 844 });
      await setTheme(page, theme);
      await expect(page.getByText(/Diesen Bereich bearbeitest du am Computer/)).toBeVisible();
      await page.screenshot({ path: `${shotDir}/elements-list-${theme}-390.png` });
    }
  } finally {
    await request.delete(`/api/templates/${template.id}`);
    await request.delete(`/api/element-definitions/${program.id}`);
    await request.delete(`/api/element-definitions/${tasks.id}`);
    await request.delete(`/api/element-definitions/${single.id}`);
  }
});
