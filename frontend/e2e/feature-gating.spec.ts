import { test, expect, request as playwrightRequest } from "@playwright/test";
import { authFiles } from "./auth";

// Feature-Gating pro Mandant (Finanzen als Pilot-Feature): orthogonal zur Rollenpruefung
// (roles-and-tenants.spec.ts). Der Nav-Link verschwindet und der Direktzugriff auf
// /finances wird blockiert, sobald der Mandant Finanzen nicht (mehr) gebucht hat - zwei
// unabhaengige Schichten (Nav + Seiten-Guard), zusaetzlich zur Backend-Route, die schon
// vorher per require_feature durchgesetzt wird. Ein einziger Test statt getrennter API-/
// UI-Specs, damit nur ein disable/enable-Zyklus auf dem geteilten Demo-Mandanten laeuft -
// zwei parallele Specs, die dieselbe Tenant-Feature-Zeile umschalten, waeren sonst ein
// Race (siehe storage-quota.spec.ts fuer dasselbe Muster bei der Speicherkontingent-Zeile).
test("disabling the finance feature hides the nav link and blocks the finance routes", async ({ page }) => {
  const writerApi = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.writer });
  const adminApi = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.platformAdmin });
  let tenantId: string | undefined;
  try {
    const session = await (await writerApi.get("/api/auth/session")).json();
    tenantId = session.current_tenant.id as string;
    expect(session.current_tenant.enabled_features).toContain("finance");

    await page.goto("/finances");
    await expect(page).not.toHaveURL(/\/login/);
    // .nav-link statt eines bloßen href-Selektors: /finances trägt sowohl den Sidebar-Link als
    // auch (via RouteTabs) einen "Konten"-Tab mit demselben href - nur der Sidebar-Link ist
    // hier relevant.
    await expect(page.locator('.nav-link[href="/finances"]')).toBeVisible();

    const disable = await adminApi.put(`/api/admin/tenants/${tenantId}/features`, { data: { enabled_codes: [] } });
    expect(disable.ok(), await disable.text()).toBeTruthy();

    const sessionAfterDisable = await (await writerApi.get("/api/auth/session")).json();
    expect(sessionAfterDisable.current_tenant.enabled_features).not.toContain("finance");
    expect((await writerApi.get("/api/finance/accounts")).status()).toBe(403);
    expect((await writerApi.get("/api/fines")).status()).toBe(403);

    await page.goto("/finances");
    await expect(page).toHaveURL("/");
    await expect(page.locator('.nav-link[href="/finances"]')).toHaveCount(0);

    const restore = await adminApi.put(`/api/admin/tenants/${tenantId}/features`, { data: { enabled_codes: ["finance"] } });
    expect(restore.ok(), await restore.text()).toBeTruthy();

    const sessionAfterRestore = await (await writerApi.get("/api/auth/session")).json();
    expect(sessionAfterRestore.current_tenant.enabled_features).toContain("finance");
    expect((await writerApi.get("/api/finance/accounts")).status()).toBe(200);
    expect((await writerApi.get("/api/fines")).status()).toBe(200);
  } finally {
    // Immer mit gebuchtem Finanzen zurücklassen - sonst brechen andere e2e-Specs, die auf dem
    // geteilten Demo-Mandanten Finanzen/Bussen ansprechen.
    if (tenantId) {
      await adminApi.put(`/api/admin/tenants/${tenantId}/features`, { data: { enabled_codes: ["finance"] } }).catch(() => {});
    }
    await writerApi.dispose();
    await adminApi.dispose();
  }
});
