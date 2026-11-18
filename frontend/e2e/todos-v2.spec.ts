import { test, expect, APIRequestContext, Page } from "@playwright/test";

// Pendenzen v2: Liste nach Fälligkeit, Board je Person (Neuzuweisen per Menü und per Ziehen),
// Kalender-Dialog. Screenshots Light/Dark, 1440 und 390 px (390 zeigt die Mobile-Ansicht).

function isoDay(offset: number): string {
  return new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);
}

async function ok(request: APIRequestContext, method: "post" | "patch", path: string, data: unknown) {
  const response = await request[method](path, { data });
  expect(response.ok(), `${method.toUpperCase()} ${path}: ${await response.text()}`).toBeTruthy();
  return response.json();
}

async function assigneesOf(request: APIRequestContext, todoId: string): Promise<string[]> {
  const items: { id: string; assigned_participant_ids: string[] }[] = await (await request.get("/api/todos?limit=500")).json();
  return items.find((item) => item.id === todoId)?.assigned_participant_ids ?? [];
}

async function setTheme(page: Page, theme: string) {
  await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
  await page.reload();
}

test("Pendenzen v2: Liste, Board und Kalender", async ({ request, page }) => {
  test.setTimeout(240_000);
  const suffix = Date.now();
  const anna = await ok(request, "post", "/api/participants", { display_name: `Anna V2 ${suffix}` });
  const ben = await ok(request, "post", "/api/participants", { display_name: `Ben V2 ${suffix}` });
  const created: string[] = [];
  try {
    const overdue = await ok(request, "post", "/api/todos", { task: `V2 überfällig ${suffix}`, tags: ["E2E"] });
    created.push(overdue.id);
    await ok(request, "patch", `/api/protocol-todos/${overdue.id}`, { due_date: isoDay(-3), assigned_participant_ids: [anna.id] });
    const today = await ok(request, "post", "/api/todos", { task: `V2 heute ${suffix}` });
    created.push(today.id);
    await ok(request, "patch", `/api/protocol-todos/${today.id}`, { due_date: isoDay(0), assigned_participant_ids: [ben.id] });
    const loose = await ok(request, "post", "/api/todos", { task: `V2 ohne Datum ${suffix}` });
    created.push(loose.id);

    // Liste: Gruppen nach Fälligkeit, Quelle, Zuweisung
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/todos");
    await expect(page.getByRole("heading", { name: "Pendenzen", level: 1 })).toBeVisible({ timeout: 60_000 });
    await page.getByPlaceholder("Pendenzen durchsuchen").fill(`${suffix}`);
    const table = page.locator(".todo-v2-table");
    await expect(table.locator(".todo-v2-group-overdue")).toContainText("Überfällig");
    await expect(table.locator(".todo-v2-group-soon")).toContainText("Nächste 14 Tage");
    await expect(table.locator(".todo-v2-group-none")).toContainText("Ohne Fälligkeit");
    const overdueRow = table.locator("tr", { hasText: `V2 überfällig ${suffix}` });
    await expect(overdueRow).toContainText("seit 3 Tagen überfällig");
    await expect(overdueRow).toContainText(`Anna V2 ${suffix}`);
    await expect(overdueRow).toContainText("Manuell erstellt");
    await expect(table.locator("tr", { hasText: `V2 ohne Datum ${suffix}` })).toContainText("Nicht zugewiesen");
    for (const theme of ["light", "dark"]) {
      await setTheme(page, theme);
      await page.getByPlaceholder("Pendenzen durchsuchen").fill(`${suffix}`);
      await expect(table.locator(".todo-v2-group-overdue")).toBeVisible({ timeout: 30_000 });
      await page.screenshot({ path: `test-results/todos-v2-list-${theme}-1440.png`, fullPage: true });
    }
    await setTheme(page, "light");

    // Board: Tastatur-Alternative («Zuweisen an …») und Ziehen
    await page.getByPlaceholder("Pendenzen durchsuchen").fill(`${suffix}`);
    await page.getByRole("tab", { name: "Board" }).click();
    const annaColumn = page.getByRole("region", { name: `Anna V2 ${suffix}` });
    const benColumn = page.getByRole("region", { name: `Ben V2 ${suffix}` });
    const unassignedColumn = page.getByRole("region", { name: "Nicht zugewiesen" });
    await expect(annaColumn).toContainText(`V2 überfällig ${suffix}`);
    await page.screenshot({ path: "test-results/todos-v2-board-light-1440.png", fullPage: true });

    await annaColumn.getByRole("button", { name: `Zuweisen an … (V2 überfällig ${suffix})` }).click();
    await page.getByRole("menuitem", { name: `Zuweisen an Ben V2 ${suffix}` }).click();
    await expect(benColumn).toContainText(`V2 überfällig ${suffix}`);
    await expect(page.locator(".todo-board-confirmation")).toContainText(`Ben V2 ${suffix}`);
    await expect.poll(() => assigneesOf(request, overdue.id)).toEqual([ben.id]);

    await benColumn.locator(".todo-board-card", { hasText: `V2 heute ${suffix}` }).dragTo(unassignedColumn);
    await expect(unassignedColumn).toContainText(`V2 heute ${suffix}`);
    await expect.poll(() => assigneesOf(request, today.id)).toEqual([]);

    await setTheme(page, "dark");
    await page.getByPlaceholder("Pendenzen durchsuchen").fill(`${suffix}`);
    await page.getByRole("tab", { name: "Board" }).click();
    await expect(unassignedColumn).toBeVisible();
    await page.screenshot({ path: "test-results/todos-v2-board-dark-1440.png", fullPage: true });

    // Kalender-Dialog
    for (const theme of ["dark", "light"]) {
      if (theme === "light") await setTheme(page, "light");
      await page.getByRole("button", { name: "Kalender" }).click();
      const dialog = page.getByRole("dialog", { name: "Pendenzen-Kalender" });
      await expect(dialog).toBeVisible();
      await expect(dialog.locator(".todo-calendar-day-today")).toContainText(`V2 heute ${suffix}`);
      await expect(dialog.locator(".todo-calendar-side")).toContainText(`V2 überfällig ${suffix}`);
      await expect(dialog.getByRole("link", { name: /In Apple oder Google Kalender abonnieren/ })).toBeVisible();
      await page.screenshot({ path: `test-results/todos-v2-calendar-${theme}-1440.png` });
      await dialog.getByRole("button", { name: "Termine einblenden" }).click();
      await expect(dialog.getByRole("button", { name: "Termine einblenden" })).toHaveAttribute("aria-pressed", "false");
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
    }

    // 390 px: Mobile-Ansicht der Pendenzen bleibt bestehen
    await page.setViewportSize({ width: 390, height: 844 });
    for (const theme of ["light", "dark"]) {
      await setTheme(page, theme);
      await expect(page.locator(".mobile-todo-row, .mobile-empty").first()).toBeVisible({ timeout: 30_000 });
      await page.screenshot({ path: `test-results/todos-v2-mobile-${theme}-390.png`, fullPage: true });
    }
  } finally {
    await page.evaluate(() => localStorage.setItem("hocx-theme", "light")).catch(() => undefined);
    for (const id of created) await request.delete(`/api/protocol-todos/${id}`);
    for (const person of [anna, ben]) await request.delete(`/api/participants/${person.id}`);
  }
});
