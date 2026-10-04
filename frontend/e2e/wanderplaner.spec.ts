import { test, expect, request as playwrightRequest } from "@playwright/test";
import { authFiles } from "./auth";

// Die geteilte E2E-Umgebung hat kein Wegenetz. Der Erstellungsfehler wird daher
// deterministisch simuliert; der echte Planungsablauf wird im Backend gegen das
// isolierte Fixture-Netz geprüft. Lokale Via-Entwürfe werden an einer bestehenden Tour geprüft.
test("Erstellen behandelt Berechnungsfehler und Routenänderungen bleiben lokal", async ({ page }) => {
  test.setTimeout(90_000); // MapLibre-Ladezeiten (echte swisstopo-Tiles) brauchen mehr als die Default-45s
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

    await page.goto("/hiking-planner");
    await expect(page.locator(".nav-link[href=\"/hiking-planner\"]")).toBeVisible();

    await page.getByRole("button", { name: "Neue Wanderung" }).click();
    await page.getByLabel("Titel").fill("E2E Rigi Kulm ab Goldau");
    const createMap = page.locator(".wanderplaner-map");
    await expect(createMap).toBeVisible();
    // MapLibre haengt seinen Klick-Handler erst nach "load" ein (siehe hiking-tour-map.tsx) -
    // ohne Wartezeit landen die folgenden Klicks manchmal, bevor die Karte bereit ist.
    await page.waitForTimeout(1000);
    const createMapBox = await createMap.boundingBox();
    if (!createMapBox) throw new Error("Karte im Erstellen-Dialog nicht gefunden");
    // Ueber den Locator klicken (nicht page.mouse.click mit vorab gelesener boundingBox) -
    // das lässt Playwright Sichtbarkeit/Position im Klickmoment selbst pruefen, statt auf
    // moeglicherweise veraltete, vorab gelesene Koordinaten zu vertrauen. Zwei verschiedene
    // Punkte auf der (noch ganz Schweiz zeigenden) Karte anklicken - erster Klick setzt Start,
    // zweiter automatisch das Ziel (siehe hiking-tour-manager.tsx). Welche realen Koordinaten
    // das genau sind, ist fuer diesen Test irrelevant.
    await createMap.click({ position: { x: createMapBox.width * 0.3, y: createMapBox.height * 0.5 } });
    await expect(page.getByRole("button", { name: /Start setzen/ })).toContainText("✓");
    await createMap.click({ position: { x: createMapBox.width * 0.7, y: createMapBox.height * 0.5 } });
    await expect(page.getByRole("button", { name: /Ziel setzen/ })).toContainText("✓");
    await page.route("**/api/hiking-tours/planned", (route) => route.fulfill({
      status: 422, contentType: "application/json", body: JSON.stringify({ detail: "Test: Berechnung nicht verfügbar" }),
    }));
    await page.getByRole("button", { name: "Wanderung erstellen" }).click();
    await expect(page.getByText("Test: Berechnung nicht verfügbar")).toBeVisible();
    await expect(page.getByRole("dialog", { name: "Neue Wanderung" })).toBeVisible();
    await page.getByRole("button", { name: "Schliessen", exact: true }).click();

    const created = await writerApi.post("/api/hiking-tours", {
      data: { title: "E2E Rigi Kulm ab Goldau", start: { lat: 47, lon: 8.5 }, end: { lat: 47, lon: 8.52 } },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const tour = await created.json();
    await page.goto(`/hiking-planner/${tour.id}`);
    await expect(page.getByRole("heading", { name: tour.title })).toBeVisible();
    await expect(page.getByRole("button", { name: "Route berechnen" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Höhenprofil abrufen" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Automatisch analysieren" })).toHaveCount(0);
    await page.getByRole("button", { name: "Via-Punkt hinzufügen" }).click();
    const detailMap = page.locator(".wanderplaner-map");
    const detailBox = await detailMap.boundingBox();
    if (!detailBox) throw new Error("Detailkarte nicht gefunden");
    await detailMap.click({ position: { x: detailBox.width * 0.5, y: detailBox.height * 0.5 } });
    await expect(page.getByText(/Ungespeicherte Änderungen/)).toBeVisible();
    // Vor Speichern bleibt auch die echte API unverändert.
    const persisted = await (await writerApi.get(`/api/hiking-tours/${tour.id}`)).json();
    expect(persisted.waypoints).toHaveLength(2);
    await page.getByRole("button", { name: "Änderungen verwerfen" }).click();
    await expect(page.getByText(/Ungespeicherte Änderungen/)).toHaveCount(0);

    await page.getByRole("button", { name: "Bearbeiten" }).click();
    await page.getByLabel("Titel").fill("E2E Rigi Kulm ab Goldau (bearbeitet)");
    await page.getByRole("dialog", { name: "Wanderung bearbeiten" }).getByRole("button", { name: "Speichern" }).click();
    await expect(page.getByRole("heading", { name: "E2E Rigi Kulm ab Goldau (bearbeitet)" })).toBeVisible();

    await page.getByRole("button", { name: "Löschen" }).first().click();
    await page.getByRole("button", { name: "Löschen" }).last().click();
    await expect(page).toHaveURL("/hiking-planner");
    await expect(page.getByText("E2E Rigi Kulm ab Goldau (bearbeitet)")).toHaveCount(0);
  } finally {
    if (tenantId) {
      await adminApi.put(`/api/admin/tenants/${tenantId}/features`, { data: { enabled_codes: originalFeatures } }).catch(() => {});
    }
    await writerApi.dispose();
    await adminApi.dispose();
  }
});
