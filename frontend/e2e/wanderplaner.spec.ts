import { test, expect, request as playwrightRequest } from "@playwright/test";
import { authFiles } from "./auth";

// Wanderplaner Phase 1 (Basis-CRUD): Tour erstellen -> Start/Ziel als Wegpunkte sehen ->
// Via-Punkt hinzufuegen -> Tour bearbeiten -> Via-Punkt entfernen -> Tour loeschen. Karte,
// Routing, Marschzeit, Analyse, Druck folgen erst in spaeteren Phasen (siehe Wiki-Seite
// "Wanderplaner") und sind hier bewusst nicht Teil des Flows.
test("Tour erstellen, Wegpunkt hinzufuegen/entfernen und wieder loeschen", async ({ page }) => {
  const writerApi = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.writer });
  const adminApi = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.platformAdmin });
  let tenantId: string | undefined;
  let originalFeatures: string[] = [];
  try {
    const session = await (await writerApi.get("/api/auth/session")).json();
    tenantId = session.current_tenant.id as string;
    originalFeatures = session.current_tenant.enabled_features as string[];

    const enable = await adminApi.put(`/api/admin/tenants/${tenantId}/features`, {
      data: { enabled_codes: [...originalFeatures, "wanderplaner"] },
    });
    expect(enable.ok(), await enable.text()).toBeTruthy();

    await page.goto("/wanderplaner");
    await expect(page.locator(".nav-link[href=\"/wanderplaner\"]")).toBeVisible();

    await page.getByRole("button", { name: "Neue Wanderung" }).click();
    await page.getByLabel("Titel").fill("E2E Rigi Kulm ab Goldau");
    await page.getByLabel("Start – Breite (Lat)").fill("47.0512");
    await page.getByLabel("Start – Länge (Lon)").fill("8.5478");
    await page.getByLabel("Ziel – Breite (Lat)").fill("47.0576");
    await page.getByLabel("Ziel – Länge (Lon)").fill("8.4883");
    await page.getByRole("button", { name: "Wanderung erstellen" }).click();

    await expect(page).toHaveURL(/\/wanderplaner\/.+/);
    await expect(page.getByRole("heading", { name: "E2E Rigi Kulm ab Goldau" })).toBeVisible();
    await expect(page.getByText("Start", { exact: true })).toBeVisible();
    await expect(page.getByText("Ziel", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Via-Punkt hinzufügen" }).click();
    await page.getByLabel("Bezeichnung").fill("Kloesterli");
    await page.locator('label:has-text("Breite (Lat)") input').fill("47.0489");
    await page.locator('label:has-text("Länge (Lon)") input').fill("8.4949");
    await page.getByRole("button", { name: "Hinzufügen", exact: true }).click();
    await expect(page.getByText("Kloesterli")).toBeVisible();

    await page.getByRole("row", { name: /Kloesterli/ }).getByRole("button", { name: "Entfernen" }).click();
    await page.getByRole("button", { name: "Entfernen" }).last().click();
    await expect(page.getByText("Kloesterli")).toHaveCount(0);

    await page.getByRole("button", { name: "Bearbeiten" }).click();
    await page.getByLabel("Titel").fill("E2E Rigi Kulm ab Goldau (bearbeitet)");
    await page.getByRole("button", { name: "Speichern" }).click();
    await expect(page.getByRole("heading", { name: "E2E Rigi Kulm ab Goldau (bearbeitet)" })).toBeVisible();

    await page.getByRole("button", { name: "Löschen" }).first().click();
    await page.getByRole("button", { name: "Löschen" }).last().click();
    await expect(page).toHaveURL("/wanderplaner");
    await expect(page.getByText("E2E Rigi Kulm ab Goldau (bearbeitet)")).toHaveCount(0);
  } finally {
    if (tenantId) {
      await adminApi.put(`/api/admin/tenants/${tenantId}/features`, { data: { enabled_codes: originalFeatures } }).catch(() => {});
    }
    await writerApi.dispose();
    await adminApi.dispose();
  }
});
