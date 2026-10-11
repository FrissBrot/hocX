import { test, expect } from "@playwright/test";

test("Stammlisten: Vorschau, Zuordnung, Suche und Unbesetzt-Filter", async ({ page }) => {
  test.setTimeout(90_000);
  const name = `Gruppen ${Date.now()}`;
  const response = await page.request.post("/api/lists", { data: {
    name, description: "Leitende pro Gruppe", column_one_title: "Gruppe", column_one_value_type: "text",
    column_two_title: "Leitende", column_two_value_type: "participants", is_active: true,
  } });
  expect(response.ok()).toBeTruthy();
  const definition = await response.json();
  const participantResponse = await page.request.post("/api/participants", { data: { display_name: `Noah Durrer ${Date.now()}` } });
  expect(participantResponse.ok()).toBeTruthy();
  const person = await participantResponse.json();
  for (const [index, label] of ["Wölfe", "Füchse"].entries()) {
    const entry = await page.request.post(`/api/lists/${definition.id}/entries`, { data: {
      sort_index: index, column_one_value: { text_value: label }, column_two_value: { participant_ids: index ? [] : [person.id] },
    } });
    expect(entry.ok()).toBeTruthy();
  }
  try {
    await page.goto("/lists");
    await page.getByRole("tab", { name: new RegExp(name) }).click();
    await expect(page.getByRole("button", { name: `${person.display_name} entfernen` })).toBeVisible();
    await page.getByRole("button", { name: "1 unbesetzt" }).click();
    await expect(page.locator(".list-manager-table-shell input[value='Wölfe']")).toHaveCount(0);
    await expect(page.locator(".list-manager-table-shell input[value='Füchse']")).toBeVisible();
    await page.getByRole("button", { name: "1 unbesetzt" }).click();
    await page.getByPlaceholder(`In «${name}» suchen`).fill(person.display_name);
    await expect(page.locator(".list-manager-table-shell input[value='Füchse']")).toHaveCount(0);
    await page.getByPlaceholder(`In «${name}» suchen`).fill("");
    for (const theme of ["light", "dark"]) {
      for (const width of [1440, 390]) {
        await page.setViewportSize({ width, height: 1000 });
        // Theme vor dem Reload setzen: nachträglich gesetzt gleicht die App es asynchron ab,
        // rendert neu und schliesst dabei einen schon geöffneten Dialog (CI, Dark-Durchlauf).
        await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
        await page.reload();
        if (width === 1440) {
          await page.getByRole("tab", { name: new RegExp(name) }).click();
          await expect(page.getByRole("button", { name: `${person.display_name} entfernen` })).toBeVisible();
        }
        await page.screenshot({ path: `test-results/lists-${theme}-${width}.png`, fullPage: true });
        if (width === 1440) {
          await page.getByRole("button", { name: "+ Neue Liste", exact: true }).click();
          const dialog = page.getByRole("dialog", { name: "Liste erstellen" });
          await expect(dialog).toBeVisible();
          await dialog.getByRole("group", { name: "Spalte 2", exact: true }).getByRole("button", { name: /Ein Termin/ }).click();
          await expect(dialog.locator(".list-definition-preview")).toContainText("Herbstlager");
          await page.screenshot({ path: `test-results/lists-dialog-${theme}-${width}.png`, fullPage: true });
          await dialog.getByRole("button", { name: "Abbrechen" }).click();
        }
      }
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.reload();
    await page.getByRole("tab", { name: new RegExp(name) }).click();
    await page.getByRole("button", { name: `${person.display_name} entfernen` }).click();
    await expect(page.getByRole("button", { name: "2 unbesetzt" })).toBeVisible();
    await page.reload();
    await page.getByRole("tab", { name: new RegExp(name) }).click();
    await expect(page.getByRole("button", { name: "2 unbesetzt" })).toBeVisible();
  } finally {
    await page.request.delete(`/api/lists/${definition.id}`);
    await page.request.delete(`/api/participants/${person.id}`);
  }
});
