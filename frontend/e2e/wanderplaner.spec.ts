import { test, expect, request as playwrightRequest } from "@playwright/test";
import { authFiles } from "./auth";

// Wanderplaner Phase 1+2: Tour per Kartenklick erstellen (Start/Ziel) -> Wegpunkte sehen ->
// Via-Punkt per Kartenklick hinzufuegen/entfernen -> Route berechnen (Button-Verdrahtung,
// siehe Kommentar unten zum Grund fuer die tolerante Assertion) -> Tour bearbeiten -> loeschen.
// Hoehenprofil/Marschzeit (Phase 3) und automatische Analyse (Phase 4, "Automatisch
// analysieren"-Button in hiking-tour-detail.tsx) sind hier bewusst NICHT Teil des Flows: die
// geteilte E2E-Umgebung hat kein importiertes Wegenetz (siehe
// scripts/import_routing_network.py-Docstring), "Route berechnen" schlaegt darum erwartungs-
// gemaess fehl, und beide Folge-Features setzen eine erfolgreich berechnete Route voraus.
// Ihre fachliche Korrektheit ist bereits durch Backend-Integrationstests gegen das
// Fixture-Wegenetz abgedeckt (test_hiking_tour_analysis_service.py u.a.). Rekognoszierung und
// Druck folgen erst in spaeteren Phasen (siehe Wiki-Seite "Wanderplaner").
test("Tour per Karte erstellen, Route berechnen, Wegpunkt hinzufuegen/entfernen und wieder loeschen", async ({ page }) => {
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

    await page.goto("/wanderplaner");
    await expect(page.locator(".nav-link[href=\"/wanderplaner\"]")).toBeVisible();

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
    await page.getByRole("button", { name: "Wanderung erstellen" }).click();

    // Grosszuegiger Timeout: die dynamische Detailroute (/wanderplaner/[id]) kompiliert im
    // Next.js-Dev-Server (siehe docker-compose.dev.yml, auch der geteilte E2E-Stack laeuft im
    // Dev-Modus) bei ihrem allerersten Besuch on-demand nach - laenger als das Standard-
    // Timeout, wenn diese Route seit einem Server-Neustart noch nie kompiliert wurde.
    await expect(page).toHaveURL(/\/wanderplaner\/.+/, { timeout: 15_000 });
    await expect(page.getByRole("heading", { name: "E2E Rigi Kulm ab Goldau" })).toBeVisible();
    await expect(page.getByText("Start", { exact: true })).toBeVisible();
    await expect(page.getByText("Ziel", { exact: true })).toBeVisible();

    await page.waitForTimeout(1000); // Karte auf der Detailseite laedt neu (eigene MapLibre-Instanz)
    await page.getByRole("button", { name: "Via-Punkt hinzufügen" }).click();
    const detailMap = page.locator(".wanderplaner-map");
    const detailMapBox = await detailMap.boundingBox();
    if (!detailMapBox) throw new Error("Karte in der Detailansicht nicht gefunden");
    await detailMap.click({ position: { x: detailMapBox.width / 2, y: detailMapBox.height / 2 } });
    await expect(page.getByText("Via-Punkt hinzugefügt")).toBeVisible();
    await expect(page.getByText("Via-Punkt", { exact: true })).toBeVisible();

    // Route berechnen: prueft nur, dass Button/Request verdrahtet sind (Erfolg ODER ein
    // erwarteter "kein Routing möglich"-Fehler sind beide gueltig - die geteilte E2E-Umgebung
    // hat kein importiertes Wegenetz, siehe scripts/import_routing_network.py-Docstring: der
    // Import ist ein separater Betriebsschritt, nicht Teil dieses Test-Deploys). Die fachliche
    // Routing-Korrektheit selbst ist bereits durch test_routing_service.py abgedeckt.
    await page.getByRole("button", { name: "Route berechnen" }).click();
    await expect(page.locator(".app-toast").first()).toBeVisible({ timeout: 10_000 });

    await page.getByRole("row", { name: /Via-Punkt/ }).getByRole("button", { name: "Entfernen" }).click();
    await page.getByRole("button", { name: "Entfernen" }).last().click();
    await expect(page.getByText("Punkt entfernt")).toBeVisible();

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
