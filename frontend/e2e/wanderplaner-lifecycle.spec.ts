import { test, expect, request as playwrightRequest } from "@playwright/test";
import path from "node:path";
import { authFiles } from "./auth";

// Wanderplaner Phase 3-7: Hoehenprofil/Marschzeit, automatische Analyse, Rekognoszierung/
// Freigabe, Druck-PDF, GPX-Import/-Export. Anders als wanderplaner.spec.ts (Phase 1+2, testet
// die Kartenklick-Erstellung selbst) legt dieser Test die Tour direkt per API mit den festen
// Koordinaten des Test-Fixture-Wegenetzes an (wanderplaner-backend/tests/fixtures/routing_network_sample.geojson)
// und prueft die UI-Folgeschritte im Browser - ein Kartenklick auf exakt diese winzige
// Netzflaeche (Zug, ca. 8.50-8.52 Grad Ost) waere ueber Pixelkoordinaten kaum zuverlaessig
// zu treffen. Braucht ein importiertes Wegenetz (siehe
// wanderplaner-backend/scripts/import_routing_network.py-Docstring) - in der geteilten E2E-Umgebung normalerweise
// nicht vorhanden, deshalb bislang nicht Teil des Standard-E2E-Laufs (siehe Wiki
// "Wanderplaner", Phase-7-Notiz).
const A = { lat: 47.0, lon: 8.5 };
const C = { lat: 47.0, lon: 8.52 };

test.describe("Wanderplaner: Hoehenprofil, Analyse, Rekognoszierung, Druck, GPX", () => {
  test.setTimeout(120_000);

  let writerApi: Awaited<ReturnType<typeof playwrightRequest.newContext>>;
  let adminApi: Awaited<ReturnType<typeof playwrightRequest.newContext>>;
  let tenantId: string | undefined;
  let originalFeatures: string[] = [];

  test.beforeEach(async () => {
    writerApi = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.writer });
    adminApi = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.platformAdmin });
    const session = await (await writerApi.get("/api/auth/session")).json();
    tenantId = session.current_tenant.id as string;
    originalFeatures = session.current_tenant.enabled_features as string[];
    const enable = await adminApi.put(`/api/admin/tenants/${tenantId}/features`, {
      data: { enabled_codes: [...originalFeatures, "wanderplaner"] },
    });
    expect(enable.ok(), await enable.text()).toBeTruthy();
  });

  test.afterEach(async () => {
    if (tenantId) {
      await adminApi.put(`/api/admin/tenants/${tenantId}/features`, { data: { enabled_codes: originalFeatures } }).catch(() => {});
    }
    await writerApi.dispose();
    await adminApi.dispose();
  });

  async function createRoutedTour(title: string) {
    const created = await writerApi.post("/api/hiking-tours", {
      data: { title, start: A, end: C, via_points: [], routing_profile: "wanderwege_bevorzugen" },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const tour = await created.json();
    const routed = await writerApi.post(`/api/hiking-tours/${tour.id}/route`, { data: {} });
    expect(routed.ok(), await routed.text()).toBeTruthy();
    return tour.id as string;
  }

  test("Hoehenprofil abrufen und automatisch analysieren", async ({ page }) => {
    const tourId = await createRoutedTour("E2E Lifecycle Hoehenprofil");
    await page.goto(`/hiking-planner/${tourId}`);
    await expect(page.getByRole("heading", { name: "E2E Lifecycle Hoehenprofil" })).toBeVisible({ timeout: 15_000 });

    await expect(page.getByRole("button", { name: "Höhenprofil abrufen" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Automatisch analysieren" })).toHaveCount(0);
    await page.getByRole("button", { name: "Speichern", exact: true }).click();
    await expect(page.getByText("Wanderung gespeichert und neu berechnet", { exact: true })).toBeVisible({ timeout: 90_000 });
    await expect(page.getByRole("heading", { name: "Wegpunkte & Marschtabelle" })).toBeVisible();

  });

  test("Rekognoszierung und Freigabe", async ({ page }) => {
    const tourId = await createRoutedTour("E2E Lifecycle Rekognoszierung");
    await page.goto(`/hiking-planner/${tourId}`);
    await expect(page.getByRole("heading", { name: "E2E Lifecycle Rekognoszierung" })).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: "Rekognoszierung" }).click();
    await page.getByLabel("Wegzustand geprüft").check();
    await page.getByLabel("Weitere Bemerkungen").fill("Weg trocken, keine Besonderheiten.");
    await page.getByRole("button", { name: "Als rekognosziert markieren" }).click();
    await expect(page.getByText("Rekognoszierung gespeichert")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Rekognosziert", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Freigeben" }).click();
    await page.getByRole("button", { name: "Freigeben" }).last().click(); // useConfirm-Rueckfrage
    await expect(page.getByText("Wanderung freigegeben")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Freigegeben", { exact: true })).toBeVisible();
  });

  test("Druck-PDF erstellen", async ({ page }) => {
    const tourId = await createRoutedTour("E2E Lifecycle Druck");
    await page.goto(`/hiking-planner/${tourId}`);
    await expect(page.getByRole("heading", { name: "E2E Lifecycle Druck" })).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: "Drucken" }).click();
    await page.getByRole("button", { name: "PDF erstellen" }).click();
    await expect(page.getByText("Druck-PDF erstellt")).toBeVisible({ timeout: 90_000 }); // WMTS-Kacheln + pdflatex
    await expect(page.getByRole("link", { name: "PDF herunterladen" })).toBeVisible();
  });

  test("GPX exportieren", async ({ page }) => {
    const tourId = await createRoutedTour("E2E Lifecycle GPX Export");
    await page.goto(`/hiking-planner/${tourId}`);
    await expect(page.getByRole("heading", { name: "E2E Lifecycle GPX Export" })).toBeVisible({ timeout: 15_000 });

    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("link", { name: "GPX exportieren" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.gpx$/);
  });

  test("GPX importieren legt eine neue Tour an", async ({ page }) => {
    await page.goto("/hiking-planner");
    await expect(page.locator(".nav-link[href=\"/hiking-planner\"]")).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: "GPX importieren" }).click();
    await page.getByLabel("Titel").fill("E2E Lifecycle GPX Import");
    await page.setInputFiles('input[type="file"]', path.join(__dirname, "fixtures", "rigi-kulm.gpx"));
    await page.getByRole("button", { name: "Importieren", exact: true }).click();

    await expect(page).toHaveURL(/\/hiking-planner\/.+/, { timeout: 90_000 });
    await expect(page.getByRole("heading", { name: "E2E Lifecycle GPX Import" })).toBeVisible();
    // Die GPX-Datei benennt Start/Ziel explizit ("Start"/"Ziel") - der Import uebernimmt das
    // als Wegpunkt-Label (siehe gpx_service.py), deshalb erscheint der Text hier doppelt
    // (Typ-Badge UND Bezeichnung-Spalte), anders als bei der Kartenklick-Erstellung ohne
    // Label in wanderplaner.spec.ts - .first() genuegt, beide belegen denselben Wegpunkt.
    await expect(page.getByText("Start", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Ziel", { exact: true }).first()).toBeVisible();
  });
});
