import { test, expect, request as playwrightRequest, APIRequestContext } from "@playwright/test";
import { authFiles } from "./auth";

// Einzelabgabe mit mehreren Abgabeelementen (Migration 0198): im Assistenten Elemente mit Name,
// Stichtag und Verantwortlichen anlegen; im Detail erscheint je Element eine eigene Kachel.

test.use({ storageState: authFiles.admin });

const suffix = `${Date.now()}`;
const title = `E2E Einzel ${suffix}`;
const personName = `E2E Verantwortlich ${suffix}`;

test.describe("Einzelabgabe mit mehreren Elementen", () => {
  let api: APIRequestContext;
  let participantId: string | undefined;

  test.beforeAll(async () => {
    api = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.admin });
    const created = await api.post("/api/participants", { data: { display_name: personName, first_name: "E2E", last_name: `Verantwortlich ${suffix}` } });
    expect(created.ok(), await created.text()).toBeTruthy();
    participantId = (await created.json()).id;
  });

  test.afterAll(async () => {
    const list = await api.get("/api/submission-assignments");
    if (list.ok()) {
      for (const assignment of (await list.json()) as { id: string; title: string }[]) {
        if (assignment.title === title) await api.delete(`/api/submission-assignments/${assignment.id}`).catch(() => {});
      }
    }
    if (participantId) await api.delete(`/api/participants/${participantId}`).catch(() => {});
    await api.dispose();
  });

  test("Elemente im Assistenten anlegen und als Kacheln sehen", async ({ page }, testInfo) => {
    await page.goto("/submission-assignments", { timeout: 30_000 });
    await page.getByRole("button", { name: "+ Abgabe" }).first().click();
    const dialog = page.getByRole("dialog").filter({ has: page.locator(".subm-edit-steps") });
    await dialog.getByLabel("Titel").fill(title);
    await dialog.getByRole("radio", { name: /Einzelabgabe/ }).click();
    await dialog.getByRole("button", { name: "Weiter" }).click();

    // Schritt 2 «Elemente»: das erste Element trägt den Titel
    await expect(dialog.getByRole("heading", { name: "Elemente" })).toBeVisible();
    const names = dialog.getByLabel("Name", { exact: true });
    await expect(names.first()).toHaveValue(title);
    await names.first().fill("Anmeldung");
    await dialog.getByRole("button", { name: "+ Element" }).click();
    await names.nth(1).fill("Fotos");
    const end = dialog.getByLabel("Stichtag von Element 2");
    await end.fill("31.12.2030");
    await end.press("Tab");
    // Verantwortliche je Element direkt in der Zeile des Elements
    await dialog.getByRole("button", { name: "Verantwortliche für «Fotos»" }).click();
    await page.getByRole("option", { name: new RegExp(personName) }).click();
    await page.keyboard.press("Escape");
    await page.screenshot({ path: testInfo.outputPath("einzelabgabe-elemente.png") });
    await page.evaluate(() => { document.documentElement.dataset.theme = "dark"; });
    await page.screenshot({ path: testInfo.outputPath("einzelabgabe-elemente-dark.png") });
    await page.evaluate(() => { document.documentElement.dataset.theme = "light"; });

    // Schritt 3: mit Verantwortlichen gibt es den persönlichen Link
    await dialog.getByRole("button", { name: "Weiter" }).click();
    await expect(dialog.getByRole("radiogroup", { name: "Persönlicher Link" })).toBeVisible();

    await dialog.getByRole("button", { name: "Weiter" }).click();
    await dialog.getByRole("button", { name: "Weiter" }).click();
    await dialog.getByRole("button", { name: "Abgabe speichern" }).click();
    await page.getByRole("dialog").filter({ hasText: "Abgabe ist bereit" }).getByRole("button", { name: "Fertig" }).click();

    // Gespeichert: zwei Elemente, Verantwortliche und Stichtag am zweiten
    const assignments = (await (await api.get("/api/submission-assignments")).json()) as {
      title: string;
      manual_elements: { name: string; window_end: string | null; responsible_participant_ids: string[]; element_ref: string }[];
    }[];
    const saved = assignments.find((assignment) => assignment.title === title);
    expect(saved?.manual_elements.map((element) => element.name)).toEqual(["Anmeldung", "Fotos"]);
    expect(saved?.manual_elements[0].element_ref).toBe("manual");
    expect(saved?.manual_elements[1]).toMatchObject({ window_end: "2030-12-31", responsible_participant_ids: [participantId] });

    // Detail: eine Kachel je Element
    await page.locator("article.subm-card", { hasText: title }).click();
    const detail = page.getByRole("dialog");
    await expect(detail.locator(".subm-element-card")).toHaveCount(2);
    await expect(detail.locator(".subm-element-card", { hasText: "Fotos" })).toContainText(personName);
    await expect(detail.locator(".subm-element-card", { hasText: "Anmeldung" })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("einzelabgabe-detail.png"), fullPage: true });
  });
});
