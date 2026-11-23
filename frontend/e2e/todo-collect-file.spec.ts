import { test, expect, request as playwrightRequest, type APIRequestContext, type FileChooser, type Page } from "@playwright/test";
import path from "node:path";

// «Datei einsammeln» im Abschnitt Dateien von «Pendenz bearbeiten» (Design 2026-11-20):
// 1a Angebot «Datei fehlt noch?» → «Einsammeln», 1b Statuskarte «Abgabe offen» mit Link und
// «Beenden», 1c eingereichte Datei + Erfolgsbanner (echte Einreichung über die Abgabebox).
// Screenshots je Zustand Light/Dark, 1440 (Dialog) und 390 px (Mobile-Sheet) nach test-results/.

function isoDay(offset: number): string {
  return new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);
}

async function ok(request: APIRequestContext, method: "post" | "patch", url: string, data?: unknown) {
  const response = await request[method](url, data === undefined ? {} : { data });
  expect(response.ok(), `${method.toUpperCase()} ${url}: ${await response.text()}`).toBeTruthy();
  return response.json();
}

async function setTheme(page: Page, theme: string) {
  await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
  await page.reload();
}

/** Pendenzen-Liste öffnen, nach dem Titel suchen und die Pendenz antippen (erledigte: Filter «Erledigt»). */
async function openTodo(page: Page, task: string, done = false) {
  const statusFilter = page.locator(".filter-tabs-option, .mobile-segment").filter({ hasText: /^Erledigt/ }).first();
  await expect(statusFilter).toBeVisible({ timeout: 60_000 });
  if (done) await statusFilter.click();
  // Mobile-Liste (390 px): Suche hinter einem Knopf, die wenigen E2E-Pendenzen stehen direkt da
  if ((page.viewportSize()?.width ?? 1440) > 640) await page.getByPlaceholder("Pendenzen durchsuchen").first().fill(task);
  await page.getByText(task, { exact: true }).first().click();
}

function dialogOf(page: Page) {
  return page.locator(".todo-edit-modal, .mobile-sheet").last();
}

async function shoot(page: Page, name: string, task: string, ready: (page: Page) => Promise<void>, done = false) {
  for (const theme of ["light", "dark"]) {
    await setTheme(page, theme);
    await openTodo(page, task, done);
    await ready(page);
    // Dateien-Abschnitt in den sichtbaren Bereich (Sheet/Dialog scrollen selbst)
    await page.locator(".todo-collect-offer, .todo-collect-card, .todo-collect-success").first().scrollIntoViewIfNeeded();
    await dialogOf(page).screenshot({ path: `test-results/todo-collect-${name}-${theme}.png` });
    await page.keyboard.press("Escape");
  }
  await setTheme(page, "light");
}

test("Pendenz: Datei einsammeln im Abschnitt Dateien", async ({ request, page, browser }) => {
  test.setTimeout(420_000);
  const suffix = Date.now();
  const anna = await ok(request, "post", "/api/participants", { display_name: `Anna Einsammeln ${suffix}` });
  const makeTodo = async (label: string) => {
    const todo = await ok(request, "post", "/api/todos", { task: `${label} ${suffix}`, tags: ["E2E"] });
    await ok(request, "patch", `/api/protocol-todos/${todo.id}`, { due_date: isoDay(10), assigned_participant_ids: [anna.id] });
    return todo as { id: string; task: string };
  };
  const offer = await makeTodo("Bankvollmacht A");
  const running = await makeTodo("Bankvollmacht B");
  const submitted = await makeTodo("Bankvollmacht C");
  const stopping = await makeTodo("Bankvollmacht D");

  // ── 1a → 1b über die Oberfläche ──────────────────────────────────────────────────────────
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/todos");
  await openTodo(page, offer.task);
  const dialog = dialogOf(page);
  await expect(dialog.getByText("Datei fehlt noch?")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Als Abgabe einsammeln" })).toHaveCount(0);
  await shoot(page, "1a-1440", offer.task, async (p) => { await expect(dialogOf(p).getByText("Datei fehlt noch?")).toBeVisible(); });

  await openTodo(page, offer.task);
  await dialogOf(page).getByRole("button", { name: "Einsammeln" }).click();
  await expect(dialogOf(page).getByText("Abgabe offen")).toBeVisible({ timeout: 30_000 });
  await expect(dialogOf(page).getByText("Wird automatisch erledigt, sobald die Datei eingereicht ist.")).toBeVisible();
  await expect(dialogOf(page).getByLabel("Link zur Abgabe")).toHaveValue(/\/manual$/);
  await page.keyboard.press("Escape");

  // ── 1b (Abgabe über die API angelegt) ────────────────────────────────────────────────────
  await ok(request, "post", `/api/protocol-todos/${running.id}/create-submission`);
  await shoot(page, "1b-1440", running.task, async (p) => {
    await expect(dialogOf(p).getByText("Abgabe offen")).toBeVisible({ timeout: 30_000 });
    await expect(dialogOf(p).getByText(/noch keine Datei/)).toBeVisible();
  });

  // ── «Beenden»: Abgabe weg, Pendenz bleibt ────────────────────────────────────────────────
  const stopCreated = await ok(request, "post", `/api/protocol-todos/${stopping.id}/create-submission`);
  await page.reload(); // Liste neu laden: die Abgabe kam über die API
  await openTodo(page, stopping.task);
  await dialogOf(page).getByRole("button", { name: "Beenden" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Beenden" }).click();
  await expect(dialogOf(page).getByText("Datei fehlt noch?")).toBeVisible({ timeout: 30_000 });
  await page.keyboard.press("Escape");
  const assignments: { id: string }[] = await (await request.get("/api/submission-assignments")).json();
  expect(assignments.some((item) => item.id === stopCreated.assignment_id)).toBe(false);
  const todosAfterStop: { id: string; submission_assignment_id: string | null; todo_status_code: string }[] = await (await request.get("/api/todos?limit=500")).json();
  expect(todosAfterStop.find((item) => item.id === stopping.id)).toMatchObject({ submission_assignment_id: null, todo_status_code: "open" });

  // ── 1c: echte Einreichung über die öffentliche Abgabebox ─────────────────────────────────
  const created = await ok(request, "post", `/api/protocol-todos/${submitted.id}/create-submission`);
  const elementUrl = new URL(created.element_url as string);
  const publicContext = await browser.newContext({ baseURL: process.env.E2E_ABGABEBOX_BASE_URL, storageState: undefined });
  try {
    const publicPage = await publicContext.newPage();
    await publicPage.goto(elementUrl.pathname);
    let fileChooser: FileChooser | undefined;
    await expect(async () => {
      const fileChooserPromise = publicPage.waitForEvent("filechooser", { timeout: 2_000 });
      await publicPage.locator(".drop-zone").click();
      fileChooser = await fileChooserPromise;
    }).toPass({ timeout: 45_000 });
    await fileChooser!.setFiles(path.resolve("e2e/fixtures/photos/sample.png"));
    await expect(publicPage.getByRole("button", { name: "Abgeben" })).toBeEnabled();
    // Der Sicherheitscheck (Captcha-Widget) meldet sich kurz nach dem Laden fertig; ein zu früher
    // Klick zeigt «Sicherheitscheck läuft noch» und sendet nichts - dann erneut abgeben.
    await expect(async () => {
      await publicPage.getByRole("button", { name: "Abgeben" }).click();
      await expect(publicPage.getByRole("heading", { name: "Danke, Abgabe eingegangen" })).toBeVisible({ timeout: 10_000 });
    }).toPass({ timeout: 60_000 });
  } finally {
    await publicContext.close();
  }
  const api = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: "e2e/.auth/admin.json" });
  const rescan = await api.post(`/api/submission-assignments/${created.assignment_id}/rescan-pending`);
  expect(rescan.ok(), await rescan.text()).toBeTruthy();
  await expect.poll(async () => {
    const todos: { id: string; todo_status_code: string }[] = await (await api.get("/api/todos?limit=500")).json();
    return todos.find((item) => item.id === submitted.id)?.todo_status_code;
  }, { timeout: 90_000, intervals: [2_000, 5_000] }).toBe("done");
  await api.dispose();

  await page.goto("/todos");
  await shoot(page, "1c-1440", submitted.task, async (p) => {
    await expect(dialogOf(p).getByText("Über die Abgabe eingereicht. Pendenz automatisch erledigt.")).toBeVisible({ timeout: 30_000 });
    // Die Abgabebox benennt die Datei nach Abgabe/Element um
    await expect(dialogOf(p).locator(".todo-collect-file-name")).toContainText(/\.png$/);
    await expect(dialogOf(p).getByRole("button", { name: "Erledigt" })).toHaveAttribute("aria-pressed", "true");
  }, true);

  // ── Mobile (390 px): dieselben Zustände im Pendenz-Sheet ─────────────────────────────────
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/todos");
  await shoot(page, "1a-390", stopping.task, async (p) => { await expect(dialogOf(p).getByText("Datei fehlt noch?")).toBeVisible({ timeout: 30_000 }); });
  await shoot(page, "1b-390", running.task, async (p) => { await expect(dialogOf(p).getByText("Abgabe offen")).toBeVisible({ timeout: 30_000 }); });
  await shoot(page, "1c-390", submitted.task, async (p) => {
    await expect(dialogOf(p).getByText("Über die Abgabe eingereicht. Pendenz automatisch erledigt.")).toBeVisible({ timeout: 30_000 });
  }, true);
});
