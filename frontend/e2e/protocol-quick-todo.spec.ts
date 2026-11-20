import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// «Schnelle Pendenz» im Protokoll-Editor (session-panel.tsx): Pendenz mit Person, Fälligkeit und
// «Datei als Abgabe einsammeln» nur per Tastatur anlegen; das Menü bleibt danach offen und leer,
// die Pendenz erscheint im Protokoll mit Badge «Abgabe». Screenshots (Light/Dark, 1440 px; 390 px
// zeigt die Mobile-Ansicht, die ein eigenes Pendenzen-Blatt hat) unter test-results/quick-todo/.

const SHOTS = "test-results/quick-todo";

async function post(request: APIRequestContext, path: string, data: unknown) {
  const response = await request.post(path, { data });
  expect(response.ok(), `POST ${path}: ${await response.text()}`).toBeTruthy();
  return response.json();
}

async function setTheme(page: Page, theme: "light" | "dark") {
  await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
}

test.describe("Schnelle Pendenz mit Abgabe", () => {
  let createdLinkId: string | null = null;

  test.afterAll(async ({ request }) => {
    if (createdLinkId) await request.delete(`/api/submission-links/${createdLinkId}`).catch(() => {});
  });

  test("per Tastatur erfassen, Menü bleibt offen, Abgabe wird angelegt", async ({ request, page }) => {
    test.setTimeout(180_000);
    const suffix = Date.now();
    // Abgaben brauchen einen Standard-Link
    const links = (await (await request.get("/api/submission-links")).json()) as { id: string; is_default: boolean }[];
    if (!links.some((link) => link.is_default)) {
      createdLinkId = (await post(request, "/api/submission-links", { name: `E2E Schnell ${suffix}`, is_default: true })).id;
    }
    const anna = await post(request, "/api/participants", { display_name: `Anna Muster ${suffix}`, first_name: "Anna", last_name: "Muster", email: `e2e-anna-${suffix}@example.invalid` });
    const beat = await post(request, "/api/participants", { display_name: `Beat Bär ${suffix}`, first_name: "Beat", last_name: "Bär", email: `e2e-beat-${suffix}@example.invalid` });
    const template = await post(request, "/api/templates", { name: `E2E Schnell ${suffix}`, protocol_number_pattern: "Q-{n}", title_pattern: "Schnell {dd.mm.yyyy}", auto_create_next_protocol: false });
    const definition = await post(request, "/api/element-definitions", {
      title: "Diverses",
      blocks: [{ id: 1, title: "Text", element_type_id: 1, render_type_id: 2, sort_index: 10, configuration_json: {} }],
    });
    await post(request, `/api/templates/${template.id}/elements`, { element_definition_id: definition.id, sort_index: 10 });
    const assigned = await request.put(`/api/templates/${template.id}/participants`, { data: { participant_ids: [anna.id, beat.id] } });
    expect(assigned.ok(), await assigned.text()).toBeTruthy();
    const protocol = await post(request, "/api/protocols/from-template", { template_id: template.id, protocol_date: new Date().toISOString().slice(0, 10), title: `E2E Schnell ${suffix}` });

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/protocols/${protocol.id}`);
    await expect(page.locator(".protocol-quick-actions")).toBeVisible();
    const flyout = page.locator(".quick-flyout-todo");

    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      await page.locator(".protocol-quick-actions-btn").nth(1).click();
      await expect(flyout).toHaveClass(/quick-flyout-open/);
      const task = flyout.getByRole("textbox", { name: "Aufgabe" });
      await expect(task).toBeFocused();
      await page.waitForTimeout(300);
      await page.screenshot({ path: `${SHOTS}/${theme}-1440-1-leer.png` });

      const title = `Mittag reservieren ${theme}`;
      await task.fill(title);
      await page.keyboard.press("Tab");
      const person = flyout.getByRole("combobox", { name: "Person" });
      await expect(person).toBeFocused();
      await page.keyboard.type("Mu");
      await expect(flyout.getByRole("option").first()).toContainText("Anna Muster");
      await expect(flyout.getByRole("option").first().locator(".participant-avatar")).toHaveText("AM");
      await page.screenshot({ path: `${SHOTS}/${theme}-1440-2-personen-dropdown.png` });
      await page.keyboard.press("Enter");
      await expect(person).toHaveValue(`Anna Muster ${suffix}`);
      await expect(flyout.locator(".quick-todo-field-avatar")).toHaveText("AM");

      // Fällig: smarte Daten oben
      await page.keyboard.press("Tab");
      const due = flyout.getByRole("combobox", { name: "Fällig" });
      await expect(due).toBeFocused();
      await expect(flyout.getByRole("option").first()).toContainText("Morgen");
      await page.screenshot({ path: `${SHOTS}/${theme}-1440-3-faellig-dropdown.png` });
      await page.keyboard.type("ende mon");
      await expect(flyout.getByRole("option").first()).toContainText("Ende Monat");
      await page.keyboard.press("Enter");
      await expect(due).toHaveValue(/^Ende Monat \(/);

      // Alt+A setzt den Haken, die Leertaste auf der Karte nimmt ihn weg und wieder zurück
      await page.keyboard.press("Alt+KeyA");
      const card = flyout.getByRole("checkbox", { name: /Datei als Abgabe einsammeln/ });
      await expect(card).toHaveAttribute("aria-checked", "true");
      await card.focus();
      await page.keyboard.press("Space");
      await expect(card).toHaveAttribute("aria-checked", "false");
      await page.keyboard.press("Space");
      await expect(card).toHaveAttribute("aria-checked", "true");
      await expect(flyout).toContainText("Anna reicht ohne Login ein, dann ist die Pendenz erledigt.");
      await expect(flyout.getByRole("button", { name: "Pendenz + Abgabe erstellen" })).toBeVisible();
      await page.screenshot({ path: `${SHOTS}/${theme}-1440-4-haken-person.png` });

      await page.keyboard.press("Enter");
      await expect(flyout.getByRole("status")).toContainText(`Erstellt: ${title} · mit Abgabe`, { timeout: 20_000 });
      await expect(flyout).toHaveClass(/quick-flyout-open/);
      await expect(task).toHaveValue("");
      await expect(task).toBeFocused();
      await expect(card).toHaveAttribute("aria-checked", "false");
      await page.screenshot({ path: `${SHOTS}/${theme}-1440-5-erstellt.png` });

      // Die Pendenz gehört jetzt zu einer Abgabe (Person und Frist übernommen)
      await expect.poll(async () => {
        const byBlock = (await (await request.get(`/api/protocols/${protocol.id}/block-todos`)).json()) as Record<string, { task: string; submission_assignment_id?: string | null; due_date?: string | null }[]>;
        const todo = Object.values(byBlock).flat().find((item) => item.task === title);
        return Boolean(todo?.submission_assignment_id && todo.due_date);
      }, { timeout: 15_000 }).toBe(true);
      // … und zeigt im Protokoll das Badge «Abgabe»
      await expect(page.locator(".todo-card", { hasText: "Abgabe" }).locator(".badge", { hasText: "Abgabe" }).first()).toBeVisible({ timeout: 15_000 });

      // Escape ohne Titel schliesst nur
      await page.keyboard.press("Escape");
      await expect(flyout).not.toHaveClass(/quick-flyout-open/);
    }

    // Escape mit Titel legt die Pendenz an und schliesst das Menü (wie bisher)
    await page.locator(".protocol-quick-actions-btn").nth(1).click();
    await expect(flyout).toHaveClass(/quick-flyout-open/);
    await expect(flyout.getByRole("textbox", { name: "Aufgabe" })).toBeFocused();
    await page.keyboard.type("Per Escape angelegt");
    await page.keyboard.press("Escape");
    await expect(flyout).not.toHaveClass(/quick-flyout-open/, { timeout: 15_000 });
    await expect.poll(async () => {
      const byBlock = (await (await request.get(`/api/protocols/${protocol.id}/block-todos`)).json()) as Record<string, { task: string }[]>;
      return Object.values(byBlock).flat().some((item) => item.task === "Per Escape angelegt");
    }, { timeout: 15_000 }).toBe(true);

    // 390 px: Mobile-Oberfläche mit eigenem Pendenzen-Blatt (nutzt das Minimenü nicht)
    for (const theme of ["light", "dark"] as const) {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.reload();
      await setTheme(page, theme);
      await page.waitForTimeout(800);
      await page.screenshot({ path: `${SHOTS}/${theme}-390-mobile-protokoll.png` });
    }
  });
});
