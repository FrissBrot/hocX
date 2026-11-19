import { test, expect, request as playwrightRequest, APIRequestContext } from "@playwright/test";
import { authFiles } from "./auth";

// Abgaben-Übersicht nach Design «Abgaben v4» (1.4.1): Karten statt Tabelle, Reiter mit
// Unterstrich, im Detail Filter (Alle/Abgegeben/Ausstehend), Kachelraster und das einzelne
// Element im selben Popup mit Zurück-Link.

test.use({ storageState: authFiles.admin });

const suffix = `${Date.now()}`;
const title = `E2E Übersicht ${suffix}`;

test.describe("Abgaben-Übersicht", () => {
  let api: APIRequestContext;
  let assignmentId: string | undefined;
  const eventIds: string[] = [];

  test.beforeAll(async () => {
    api = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.admin });
    const tag = `e2e-uebersicht-${suffix}`;
    for (const offset of [0, 7]) {
      const date = new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);
      const event = await api.post("/api/events", { data: { event_date: date, title: `E2E Höck ${offset} ${suffix}`, tag } });
      expect(event.ok(), await event.text()).toBeTruthy();
      eventIds.push((await event.json()).id);
    }
    const assignment = await api.post("/api/submission-assignments", {
      data: {
        title,
        public_slug: `e2e-uebersicht-${suffix}`,
        source_type: "events",
        tag_filter: tag,
        offset_days_before: 30,
        offset_days_after: 30,
        allowed_file_types: ["pdf"],
        max_files_per_element: 3,
        max_file_size_mb: 5,
        sort_order: "date",
      },
    });
    expect(assignment.ok(), await assignment.text()).toBeTruthy();
    assignmentId = (await assignment.json()).id;
  });

  test.afterAll(async () => {
    if (assignmentId) await api.delete(`/api/submission-assignments/${assignmentId}`).catch(() => {});
    for (const id of eventIds) await api.delete(`/api/events/${id}`).catch(() => {});
    await api.dispose();
  });

  test("Karten, Reiter und Detail mit Filter und Element im selben Popup", async ({ page }, testInfo) => {
    await page.goto("/submission-assignments", { timeout: 30_000 });
    await expect(page.getByRole("tab", { name: /Offen/ })).toHaveAttribute("aria-selected", "true");
    const card = page.locator("article.subm-card", { hasText: title });
    await expect(card).toBeVisible();
    await expect(card.getByText("0 von 2 eingereicht")).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("abgaben-liste.png"), fullPage: true });
    await page.evaluate(() => { document.documentElement.dataset.theme = "dark"; });
    await page.screenshot({ path: testInfo.outputPath("abgaben-liste-dark.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: testInfo.outputPath("abgaben-liste-390-dark.png"), fullPage: true });
    await page.evaluate(() => { document.documentElement.dataset.theme = "light"; });
    await page.screenshot({ path: testInfo.outputPath("abgaben-liste-390.png"), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });

    await card.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("tab", { name: /Alle\s*2/ })).toBeVisible();
    await expect(dialog.locator(".subm-element-card")).toHaveCount(2);
    await dialog.getByRole("tab", { name: /Abgegeben\s*0/ }).click();
    await expect(dialog.locator(".subm-element-card")).toHaveCount(0);
    await dialog.getByRole("tab", { name: /Ausstehend\s*2/ }).click();
    await expect(dialog.locator(".subm-element-card")).toHaveCount(2);
    await expect(dialog.getByText("Jede Datei wird vor der Freigabe per ClamAV geprüft.")).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("abgaben-detail.png") }); // ohne fullPage: der Seitenwechsel beim Vollbild schloss in der CI das Popup

    await dialog.locator(".subm-element-card").first().click();
    await expect(dialog.getByRole("button", { name: /← Termine/ })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("abgaben-element.png") });
    await dialog.getByRole("button", { name: /← Termine/ }).click();
    await expect(dialog.locator(".subm-element-card")).toHaveCount(2);
  });
});
