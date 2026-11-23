import { test, expect, APIRequestContext, Page } from "@playwright/test";

// Protokoll-Editor im Design «Termine, Listen & Pendenzen» und «Protokoll-Header»: Terminliste
// mit Kalender-Kacheln, Trennzeile und Umschalter Alle/Kommend, Stammliste mit Suche und
// Ansichts-Sortierung, Pendenzen mit Fortschritt und farbiger Fälligkeit, Kopf mit
// Workflow-Leiste. Screenshots Light/Dark bei 1440 px (unter 900 px gilt der eigene mobile
// Editor, mobile-protocol-editor.tsx - dort zur Kontrolle ein Bild bei 390 px).

async function json(request: APIRequestContext, method: "post" | "patch" | "get", path: string, data?: unknown) {
  const response = await request[method](path, data === undefined ? undefined : { data });
  expect(response.ok(), `${method.toUpperCase()} ${path}: ${await response.text()}`).toBeTruthy();
  return response.status() === 204 ? null : response.json();
}

function isoInDays(days: number) {
  return new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
}

async function shot(page: Page, name: string, fullPage = false) {
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
    await page.waitForTimeout(150);
    await page.screenshot({ path: `test-results/protocol-tables-${name}-${theme}-${page.viewportSize()?.width}.png`, fullPage });
  }
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
}

test("Termine, Listen, Pendenzen und Kopf im neuen Design", async ({ request, page }) => {
  test.setTimeout(240_000);
  const suffix = Date.now();
  const tag = `Anlass${suffix}`;
  const today = isoInDays(0);
  await json(request, "patch", "/api/tag-config", { [tag]: { color: "#2563eb" } });
  for (const [days, title] of [[-12, "Frühlingsputz"], [-3, "Vorstandsessen"], [5, "Hallentraining"], [19, "Sommerlager"]] as const) {
    await json(request, "post", "/api/events", { event_date: isoInDays(days), tag, title, location: "Turnhalle Dorf" });
  }
  const anna = await json(request, "post", "/api/participants", { display_name: `Anna Tabelle ${suffix}` });
  const list = await json(request, "post", "/api/lists", {
    name: `Ämtli ${suffix}`, is_active: true,
    columns: [{ title: "Ämtli", value_type: "text" }, { title: "Verantwortlich", value_type: "participants" }],
  });
  const [labelKey, peopleKey] = [...list.columns].sort((a: { sort_index: number }, b: { sort_index: number }) => a.sort_index - b.sort_index).map((column: { id: string }) => column.id);
  for (const [index, label] of ["Material", "Getränke", "Abwart"].entries()) {
    await json(request, "post", `/api/lists/${list.id}/entries`, {
      sort_index: index * 10, values: { [labelKey]: { text_value: label }, [peopleKey]: { participant_ids: index === 1 ? [] : [anna.id] } },
    });
  }
  const template = await json(request, "post", "/api/templates", {
    name: `E2E Tabellen ${suffix}`, protocol_number_pattern: "E2E-{n}", title_pattern: "Hock {dd.mm.yyyy}", auto_create_next_protocol: false,
  });
  const definition = await json(request, "post", "/api/element-definitions", {
    title: `Tabellen ${suffix}`,
    blocks: [
      {
        id: 1, title: "Termine", element_type_id: 7, render_type_id: 5, sort_index: 10,
        configuration_json: {
          event_filter: { tags: [tag], title: "", description: "", range: { mode: "all" }, cycle: null, use_column_filter: false, sort: "asc", limit: null },
          event_show_tag: true, event_show_location: true, event_show_description: false,
        },
      },
      { id: 2, title: "Ämtli", element_type_id: 6, render_type_id: 5, sort_index: 20, configuration_json: { linked_list_id: list.id, linked_list_highlight_empty: true } },
      { id: 3, title: "Pendenzen", element_type_id: 2, render_type_id: 3, sort_index: 30, configuration_json: {} },
    ],
  });
  await json(request, "post", `/api/templates/${template.id}/elements`, { element_definition_id: definition.id, sort_index: 10 });
  const protocol = await json(request, "post", "/api/protocols/from-template", { template_id: template.id, protocol_date: today, title: `E2E Tabellen ${suffix}` });
  const elements = await json(request, "get", `/api/protocols/${protocol.id}/elements`);
  const todoBlock = elements.flatMap((element: { blocks: { id: string; element_type_code: string | null }[] }) => element.blocks)
    .find((block: { element_type_code: string | null }) => block.element_type_code === "todo");
  expect(todoBlock).toBeTruthy();
  const todos = [
    { task: "Hallenschlüssel abgeben", tags: ["Halle"], patch: { due_date: isoInDays(-2) } },
    { task: "Lagerbudget erstellen", tags: ["Lager"], patch: { due_date: isoInDays(6) } },
    { task: "Protokoll verschicken", tags: ["Halle"], patch: { todo_status_id: 3, completed_at: new Date().toISOString() } },
    { task: "Sponsoren anfragen", tags: [], patch: { due_date: isoInDays(40) } },
  ];
  for (const item of todos) {
    const created = await json(request, "post", `/api/protocol-element-blocks/${todoBlock.id}/todos`, { task: item.task, tags: item.tags, todo_status_id: 1, created_by: null });
    await json(request, "patch", `/api/protocol-todos/${created.id}`, item.patch);
  }

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/protocols/${protocol.id}`);

  // Kopf: Workflow-Leiste mit aktuellem Schritt, Schalter und Hauptknopf
  const steps = page.getByRole("list", { name: "Ablauf des Protokolls" });
  await expect(steps.locator("[aria-current='step']")).toContainText("Geplant · Vorbereitung");
  await expect(page.getByRole("switch", { name: "Nachverfolgen" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Vorbereitung abschliessen/ })).toBeVisible();
  await expect(page.locator(".protocol-header-number")).toHaveText(/^E2E-\d+$/);

  // Termine: Kacheln, Zusammenfassung, Trennzeile, Umschalter (Tastatur)
  const events = page.locator(".event-list-grid").first();
  await expect(events.getByText("2 kommend · 2 vergangen")).toBeVisible();
  await expect(events.locator(".protocol-event-tile")).toHaveCount(4);
  await expect(events.locator(".protocol-event-separator")).toContainText("Ab Sitzung vom");
  await expect(events.locator(".protocol-event-tag").first()).toContainText(tag);
  await shot(page, "header-events");
  await page.locator(".protocol-header").screenshot({ path: "test-results/protocol-tables-header-only-light-1440.png" });
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
  await page.locator(".protocol-header").screenshot({ path: "test-results/protocol-tables-header-only-dark-1440.png" });
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
    await events.screenshot({ path: `test-results/protocol-tables-events-only-${theme}-1440.png` });
  }
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
  const allTab = events.getByRole("tab", { name: /Alle/ });
  await allTab.focus();
  await page.keyboard.press("ArrowRight");
  await expect(events.getByRole("tab", { name: /Kommend/ })).toHaveAttribute("aria-selected", "true");
  await expect(events.locator(".protocol-event-tile")).toHaveCount(2);
  await expect(events.locator(".protocol-event-separator")).toHaveCount(0);
  await events.getByRole("tab", { name: /Alle/ }).click();

  // Liste: Status-Pille, Suche, Sortierung per Spaltenkopf (Tastatur)
  const listBlock = page.locator(".linked-list-block").first();
  await listBlock.scrollIntoViewIfNeeded();
  await expect(listBlock.locator(".badge-warning")).toHaveText("Offen");
  const labels = listBlock.locator("tbody .linked-list-label > span:first-child");
  await expect(labels).toHaveText(["Material", "Getränke", "Abwart"]);
  const sortButton = listBlock.getByRole("button", { name: /^Ämtli/ });
  await sortButton.focus();
  await page.keyboard.press("Enter");
  await expect(labels).toHaveText(["Abwart", "Getränke", "Material"]);
  await shot(page, "list");
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
    await listBlock.screenshot({ path: `test-results/protocol-tables-list-only-${theme}-1440.png` });
  }
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
  await page.keyboard.press("Enter");
  await page.keyboard.press("Enter");
  await expect(labels).toHaveText(["Material", "Getränke", "Abwart"]);
  await listBlock.getByRole("textbox", { name: `In «Ämtli ${suffix}» suchen` }).fill("getr");
  await expect(labels).toHaveText(["Getränke"]);
  await listBlock.getByRole("button", { name: "Suche leeren" }).click();

  // Pendenzen: Fortschritt, Zähler an Tags, Fälligkeitsfarben, erledigte durchgestrichen an Ort
  const todoProgress = page.getByRole("progressbar", { name: "1 von 4 erledigt" });
  await todoProgress.scrollIntoViewIfNeeded();
  await expect(page.getByText("3 offen · 1 erledigt")).toBeVisible();
  // Editor 1a: statisch, bis der Block aktiviert ist (erledigte durchgestrichen, Fälligkeit farbig)
  const todoCard = page.locator('.editor-block-card[data-block-type="todo"]').first();
  await expect(todoCard.locator(".protocol-todo-static-done")).toHaveCount(1);
  await expect(todoCard.locator(".protocol-todo-static .todo-due-trigger-overdue")).toHaveCount(1);
  await todoCard.getByRole("button", { name: /bearbeiten$/ }).click();
  await expect(todoCard).toHaveClass(/editor-block-card-active/);
  await expect(page.locator(".todo-progress-count")).toHaveText("25 %");
  await expect(page.locator(".tag-filter-chip", { hasText: "Halle" }).locator(".tag-filter-chip-count")).toHaveText("2");
  const cards = todoProgress.locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' grid ')][1]").locator("article.todo-card");
  await expect(cards.nth(2)).toHaveClass(/todo-card-strike/);
  await expect(cards.nth(0).locator(".todo-due-trigger-overdue")).toBeVisible();
  await expect(cards.nth(1).locator(".todo-due-trigger-soon")).toBeVisible();
  await expect(cards.nth(0).locator(".todo-due-trigger")).toContainText("Überfällig ·");
  await expect(cards.nth(1).locator(".todo-due-trigger")).toContainText(/In \d+ Tagen/);
  await expect(cards.nth(3).locator(".todo-due-trigger-overdue, .todo-due-trigger-soon")).toHaveCount(0);
  await shot(page, "todos");
  const todoBlockLocator = todoProgress.locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' grid ')][1]");
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
    await todoBlockLocator.screenshot({ path: `test-results/protocol-tables-todos-only-${theme}-1440.png` });
  }
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
  // Fälligkeits-Badge bleibt Auslöser des Fälligkeitsmenüs; das freie Datum steht nur noch dort
  await expect(cards.locator(".todo-due-inline")).toHaveCount(0);
  await cards.nth(1).locator(".todo-due-trigger").click();
  await expect(page.locator("#due-date-portal")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#due-date-portal")).toHaveCount(0);
  // Tastatur: Badge fokussieren, Enter öffnet, Datum tippen, Enter übernimmt
  await cards.nth(3).locator(".todo-due-trigger").focus();
  await page.keyboard.press("Enter");
  const dateField = page.locator("#due-date-portal").getByRole("textbox", { name: /Freies Datum/ });
  await dateField.focus();
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.type("15.01.2027");
  await page.keyboard.press("Enter");
  await expect(cards.nth(3).locator(".todo-due-trigger")).toContainText("15.01.2027");
  await page.keyboard.press("Escape");

  // Export-Menü im Kopf
  await page.getByRole("button", { name: "Exportieren", exact: true }).click();
  await expect(page.getByRole("menuitem", { name: "PDF öffnen" })).toBeVisible();
  await page.keyboard.press("Escape");
  await shot(page, "full", true);

  // Unter 900 px: eigener mobiler Editor (unverändert), nur zur Kontrolle
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await page.waitForTimeout(1500);
  await shot(page, "mobile");
});
