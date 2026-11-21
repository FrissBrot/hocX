import { test, expect, type APIRequestContext, type Page } from "@playwright/test";

// Pendenz-Dialog (1.5.1): Dateien per Drag-and-Drop ins ganze Popup, Tastatur-Alternative
// «Datei hochladen …» in der Dateisuche, Duplikat-Rückfrage nach Inhalt (SHA-256) und stabile
// Dialoghöhe beim Öffnen der Dateisuche. Screenshots je Zustand Light/Dark nach test-results/.

const SHOTS = "test-results/todo-file-drop";

function pdf(marker: string): Buffer {
  return Buffer.from(`%PDF-1.7\n%${marker}\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n`);
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

async function openTodo(page: Page, task: string) {
  const search = page.getByPlaceholder("Pendenzen durchsuchen").first();
  await expect(search).toBeVisible({ timeout: 60_000 });
  await search.fill(task);
  await page.getByText(task, { exact: true }).first().click();
  await expect(dialog(page).getByPlaceholder("Hochgeladene Datei suchen …")).toBeVisible({ timeout: 30_000 });
}

function dialog(page: Page) {
  return page.locator(".todo-edit-modal.modal-shell");
}

/** Datei(en) per echtem DragEvent (dataTransfer mit «Files») über das Popup ziehen. */
async function dragFiles(page: Page, type: "dragenter" | "drop" | "dragleave", files: { name: string; content: string }[]) {
  const transfer = await page.evaluateHandle((entries) => {
    const data = new DataTransfer();
    for (const entry of entries) data.items.add(new File([entry.content], entry.name, { type: "application/pdf" }));
    return data;
  }, files);
  await dialog(page).locator(".todo-edit-heading").dispatchEvent(type, { dataTransfer: transfer });
}

async function dialogHeight(page: Page): Promise<number> {
  return (await dialog(page).boundingBox())!.height;
}

test("Pendenz: Datei ins Popup ziehen, Duplikat-Rückfrage, Höhe der Dateisuche stabil", async ({ request, page }, testInfo) => {
  test.setTimeout(300_000);
  const suffix = Date.now();
  const todo = await ok(request, "post", "/api/todos", { task: `Budget prüfen ${suffix}`, tags: ["E2E"] }) as { id: string; task: string };

  // Vorhandene Datei in der Ablage (für die Duplikat-Rückfrage)
  const existingName = `Budget-${suffix}.pdf`;
  const existingContent = pdf(`e2e-existing-${suffix}`);
  const uploadResponse = await request.post("/api/files/document-uploads", {
    multipart: { files: { name: existingName, mimeType: "application/pdf", buffer: existingContent } },
  });
  expect(uploadResponse.ok(), await uploadResponse.text()).toBeTruthy();
  const existingId = (await uploadResponse.json()).items[0].id as string;

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/todos");

  // ── Screenshots: Ruhezustand, Dateisuche offen, Drag-Overlay, Duplikat-Rückfrage ──────────
  const heights: Record<string, { closed: number; open: number }> = {};
  for (const theme of ["light", "dark"]) {
    await setTheme(page, theme);
    await openTodo(page, todo.task);
    const search = dialog(page).getByPlaceholder("Hochgeladene Datei suchen …");
    await expect(dialog(page).getByText("oder ins Fenster ziehen")).toBeVisible();
    await dialog(page).screenshot({ path: `${SHOTS}-1-ruhe-1440-${theme}.png` });

    const closed = await dialogHeight(page);
    await search.click();
    const listbox = page.getByRole("listbox", { name: "Dateien" });
    await expect(listbox.getByRole("option", { name: "Datei hochladen …" })).toBeVisible();
    await expect(listbox.getByRole("option", { name: new RegExp(existingName) }).first()).toBeVisible({ timeout: 15_000 });
    const opened = await dialogHeight(page);
    heights[theme] = { closed, open: opened };
    expect(opened, "Dialoghöhe darf sich beim Öffnen der Dateisuche nicht ändern").toBe(closed);
    await page.screenshot({ path: `${SHOTS}-2-suche-offen-1440-${theme}.png` });
    await search.press("Escape");
    expect(await dialogHeight(page)).toBe(closed);

    await dragFiles(page, "dragenter", [{ name: "Protokoll.pdf", content: "%PDF-1.7" }]);
    await expect(dialog(page).getByText("Loslassen zum Anhängen")).toBeVisible();
    await dialog(page).screenshot({ path: `${SHOTS}-3-overlay-1440-${theme}.png` });
    await dragFiles(page, "dragleave", [{ name: "Protokoll.pdf", content: "%PDF-1.7" }]);
    await expect(dialog(page).getByText("Loslassen zum Anhängen")).toHaveCount(0);

    await dialog(page).getByTestId("todo-file-upload-input").setInputFiles({ name: `Kopie-${suffix}.pdf`, mimeType: "application/pdf", buffer: existingContent });
    const question = page.getByRole("alertdialog");
    await expect(question.getByText(`Diese Datei gibt es schon: ${existingName}`, { exact: false })).toBeVisible({ timeout: 15_000 });
    await page.screenshot({ path: `${SHOTS}-4-duplikat-1440-${theme}.png` });
    await question.getByRole("button", { name: "Abbrechen" }).click();
    await expect(question).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(dialog(page)).toHaveCount(0);
  }
  await testInfo.attach("dialog-heights", { body: JSON.stringify(heights), contentType: "application/json" });
  console.log(`DIALOG_HEIGHTS ${JSON.stringify(heights)}`);
  await setTheme(page, "light");

  // ── Ablauf: neue Datei fallen lassen, Duplikat per Tastatur → «Bestehende anhängen» ──────
  await openTodo(page, todo.task);
  const newName = `Neu-${suffix}.pdf`;
  await dragFiles(page, "dragenter", [{ name: newName, content: `%PDF-1.7\n%e2e-new-${suffix}\n%%EOF\n` }]);
  await dragFiles(page, "drop", [{ name: newName, content: `%PDF-1.7\n%e2e-new-${suffix}\n%%EOF\n` }]);
  await expect(dialog(page).getByText("Loslassen zum Anhängen")).toHaveCount(0);
  await expect(dialog(page).getByRole("link", { name: new RegExp(newName) })).toBeVisible({ timeout: 60_000 });

  // Tastatur: Suche fokussieren, Pfeil hoch auf «Datei hochladen …», Enter öffnet die Dateiauswahl
  const search = dialog(page).getByPlaceholder("Hochgeladene Datei suchen …");
  await search.focus();
  await expect(page.getByRole("option", { name: "Datei hochladen …" })).toBeVisible();
  await search.press("ArrowUp");
  await expect(search).toHaveAttribute("aria-activedescendant", /.+/);
  const chooserPromise = page.waitForEvent("filechooser");
  await search.press("Enter");
  const chooser = await chooserPromise;
  await chooser.setFiles({ name: `Kopie-${suffix}.pdf`, mimeType: "application/pdf", buffer: existingContent });
  const question = page.getByRole("alertdialog");
  await expect(question.getByRole("button", { name: "Bestehende anhängen" })).toBeFocused({ timeout: 15_000 });
  await page.keyboard.press("Enter");
  await expect(dialog(page).getByRole("link", { name: new RegExp(existingName) })).toBeVisible();
  await expect(dialog(page).getByRole("link", { name: new RegExp(`Kopie-${suffix}`) })).toHaveCount(0);

  await dialog(page).getByRole("button", { name: "Speichern" }).click();
  await expect(dialog(page)).toHaveCount(0);
  const details = await (await request.get(`/api/protocol-todos/${todo.id}/details`)).json() as { files: { id: string; original_name: string }[] };
  expect(details.files.map((file) => file.original_name)).toEqual([newName, existingName]);
  expect(details.files[1].id).toBe(existingId);

  // ── Abbrechen: im Dialog hochgeladene, nicht gespeicherte Datei landet im Papierkorb ─────
  await openTodo(page, todo.task);
  const discardName = `Verworfen-${suffix}.pdf`;
  await dragFiles(page, "drop", [{ name: discardName, content: `%PDF-1.7\n%e2e-discard-${suffix}\n%%EOF\n` }]);
  await expect(dialog(page).getByRole("link", { name: new RegExp(discardName) })).toBeVisible({ timeout: 60_000 });
  await dialog(page).getByRole("button", { name: "Abbrechen" }).click();
  await expect(dialog(page)).toHaveCount(0);
  await expect(async () => {
    const trash = await (await request.get("/api/files/trash")).json() as { items: { original_name: string }[] };
    expect(trash.items.map((item) => item.original_name)).toContain(discardName);
  }).toPass({ timeout: 30_000 });
  const afterCancel = await (await request.get(`/api/protocol-todos/${todo.id}/details`)).json() as { files: { original_name: string }[] };
  expect(afterCancel.files.map((file) => file.original_name)).toEqual([newName, existingName]);

  // ── 390 px: Smartphones bekommen das Mobile-Sheet (ohne Dateisuche/Dropzone) ─────────────
  await page.setViewportSize({ width: 390, height: 844 });
  for (const theme of ["light", "dark"]) {
    await setTheme(page, theme);
    const sheet = page.locator(".mobile-sheet").last();
    // Erst nach der Hydrierung öffnet ein Tippen das Sheet - bis dahin wiederholen
    await expect(async () => {
      await page.getByText(todo.task, { exact: true }).first().click({ timeout: 5_000 });
      await expect(sheet).toBeVisible({ timeout: 3_000 });
    }).toPass({ timeout: 60_000 });
    await sheet.screenshot({ path: `${SHOTS}-5-mobile-390-${theme}.png` });
    await page.keyboard.press("Escape");
  }
});
