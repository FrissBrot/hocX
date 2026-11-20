import { test, expect, Page } from "@playwright/test";

// Termin-Dialog (Design «hocX Termin Dialog v3», components/events/event-dialog.tsx): Anlegen
// und Bearbeiten im selben Dialog, danach Autosave. Desktop (1440 px) über «Neuer Termin», mobil
// (390 px) über den Plus-Knopf der mobilen Terminliste. Screenshots Light/Dark je Breite.

async function shot(page: Page, name: string) {
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
    await page.screenshot({ path: `test-results/event-dialog-${name}-${theme}-${page.viewportSize()?.width}.png` });
  }
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
}

for (const width of [1440, 390]) {
  test(`Termin anlegen und bearbeiten im Termin-Dialog (${width} px)`, async ({ page, request }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width, height: width > 900 ? 1000 : 844 });
    await page.goto("/events");
    const title = `E2E Dialog ${width} ${Date.now()}`;
    let createdId: string | null = null;
    try {
      // «Neuer Termin» bzw. «+ Termin» im leeren Zustand
      if (width > 900) await page.getByRole("button", { name: /Termin$/ }).first().click();
      else await page.getByRole("button", { name: "Termin", exact: true }).click();

      const dialog = page.getByRole("dialog").filter({ has: page.getByRole("tab", { name: "Übersicht" }) });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole("tab")).toHaveText(["Übersicht", /Teilnehmer & Status/, "Weitere Felder"]);
      const create = dialog.getByRole("button", { name: "Termin erstellen" });
      await expect(create).toBeDisabled();
      await shot(page, "neu");

      await dialog.getByLabel("Titel", { exact: true }).fill(title);
      await dialog.getByPlaceholder("z. B. Gemeinschaftshaus, Sportplatz").fill("Turnhalle");
      const created = page.waitForResponse((response) => response.url().endsWith("/api/events") && response.request().method() === "POST");
      await create.click();
      const response = await created;
      expect(response.ok()).toBeTruthy();
      createdId = (await response.json()).id;

      // Gleicher Dialog, jetzt mit Autosave
      await expect(create).toBeHidden();
      await expect(dialog.getByRole("status")).toContainText(/automatisch gespeichert|Alle Änderungen gespeichert/);
      const saved = page.waitForResponse((r) => r.url().includes(`/api/events/${createdId}`) && r.request().method() === "PATCH");
      await dialog.getByRole("tab", { name: /Teilnehmer & Status/ }).click();
      await dialog.getByRole("checkbox", { name: /Termin abgesagt/ }).check();
      expect((await saved).ok()).toBeTruthy();
      await expect(dialog.getByRole("status")).toContainText("Alle Änderungen gespeichert");
      await shot(page, "teilnehmer");
      await dialog.getByRole("tab", { name: "Weitere Felder" }).click();
      await shot(page, "weitere");
      await dialog.getByRole("tab", { name: "Übersicht" }).click();
      await shot(page, "bearbeiten");

      const all: { id: string }[] = await (await request.get("/api/events")).json();
      const stored = all.find((item) => item.id === createdId);
      expect(stored).toMatchObject({ title, location: "Turnhalle", is_cancelled: true });
    } finally {
      if (createdId) await request.delete(`/api/events/${createdId}`);
    }
  });
}
