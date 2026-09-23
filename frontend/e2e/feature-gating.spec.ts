import { test, expect, request as playwrightRequest } from "@playwright/test";
import { authFiles } from "./auth";

const ALL_DEMO_FEATURES = ["finance", "abgabebox"];

// Feature-Gating pro Mandant (Finanzen als Pilot-Feature, seit 0085_plan_pricing auch
// Abgabebox): orthogonal zur Rollenpruefung (roles-and-tenants.spec.ts). Der Nav-Link
// verschwindet und der Direktzugriff auf die jeweilige Seite wird blockiert, sobald der
// Mandant das Feature nicht (mehr) gebucht hat - zwei unabhaengige Schichten (Nav +
// Seiten-Guard), zusaetzlich zur Backend-Route, die schon vorher per require_feature
// durchgesetzt wird. Ein einziger Test fuer beide Features statt getrennter Specs, damit
// nur ein disable/enable-Zyklus auf dem geteilten Demo-Mandanten laeuft - zwei parallele
// Specs, die dieselbe Tenant-Feature-Zeile umschalten, waeren sonst ein Race (siehe
// storage-quota.spec.ts fuer dasselbe Muster bei der Speicherkontingent-Zeile).
test("disabling finance/abgabebox hides the nav links and blocks the routes", async ({ page }) => {
  const writerApi = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.writer });
  const adminApi = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.platformAdmin });
  let tenantId: string | undefined;
  let publicApi: Awaited<ReturnType<typeof playwrightRequest.newContext>> | undefined;
  try {
    const session = await (await writerApi.get("/api/auth/session")).json();
    tenantId = session.current_tenant.id as string;
    for (const code of ALL_DEMO_FEATURES) {
      expect(session.current_tenant.enabled_features).toContain(code);
    }

    // Der Abgabebox-Link-Token wird VOR dem Disable geholt - sobald Abgabebox deaktiviert ist,
    // 403et auch GET /api/submission-links (require_abgabebox_write), wie jede andere
    // Abgabebox-Route der Haupt-App.
    const linksResponse = await writerApi.get("/api/submission-links");
    expect(linksResponse.ok(), await linksResponse.text()).toBeTruthy();
    const links = (await linksResponse.json()) as { token: string; is_default: boolean }[];
    const linkToken = (links.find((link) => link.is_default) ?? links[0])?.token;
    expect(linkToken, "tenant has no Abgabe link").toBeTruthy();
    // Ueber die echte abgabebox-frontend-Origin (nicht direkt gegen den Backend-Port), damit
    // dieselbe Same-Origin-Proxy-Route laeuft, die auch ein echter Besucher-Browser nimmt
    // (siehe publicApiUrl in abgabebox-frontend/lib/api.ts).
    publicApi = await playwrightRequest.newContext({ baseURL: process.env.E2E_ABGABEBOX_BASE_URL });

    await page.goto("/finances");
    await expect(page).not.toHaveURL(/\/login/);
    // .nav-link statt eines bloßen href-Selektors: /finances trägt sowohl den Sidebar-Link als
    // auch (via RouteTabs) einen "Konten"-Tab mit demselben href - nur der Sidebar-Link ist
    // hier relevant.
    await expect(page.locator('.nav-link[href="/finances"]')).toBeVisible();
    await expect(page.locator('.nav-link[href="/submission-assignments"]')).toBeVisible();

    const disable = await adminApi.put(`/api/admin/tenants/${tenantId}/features`, { data: { enabled_codes: [] } });
    expect(disable.ok(), await disable.text()).toBeTruthy();

    const sessionAfterDisable = await (await writerApi.get("/api/auth/session")).json();
    for (const code of ALL_DEMO_FEATURES) {
      expect(sessionAfterDisable.current_tenant.enabled_features).not.toContain(code);
    }
    expect((await writerApi.get("/api/finance/accounts")).status()).toBe(403);
    expect((await writerApi.get("/api/fines")).status()).toBe(403);
    expect((await writerApi.get("/api/submission-assignments")).status()).toBe(403);

    // Der Link-Token bleibt gueltig, aber der externe Teilnehmer soll "nicht verfuegbar" statt
    // eines rohen 404 sehen (siehe FEATURE_DISABLED in abgabebox-backend/app/routes/public.py).
    const publicAssignmentsDisabled = await publicApi.get(`/api/public/${linkToken}/assignments`);
    expect(publicAssignmentsDisabled.status()).toBe(403);

    await page.goto("/finances");
    await expect(page).toHaveURL("/");
    await expect(page.locator('.nav-link[href="/finances"]')).toHaveCount(0);

    await page.goto("/submission-assignments");
    await expect(page).toHaveURL("/");
    await expect(page.locator('.nav-link[href="/submission-assignments"]')).toHaveCount(0);

    const restore = await adminApi.put(`/api/admin/tenants/${tenantId}/features`, { data: { enabled_codes: ALL_DEMO_FEATURES } });
    expect(restore.ok(), await restore.text()).toBeTruthy();

    const sessionAfterRestore = await (await writerApi.get("/api/auth/session")).json();
    for (const code of ALL_DEMO_FEATURES) {
      expect(sessionAfterRestore.current_tenant.enabled_features).toContain(code);
    }
    expect((await writerApi.get("/api/finance/accounts")).status()).toBe(200);
    expect((await writerApi.get("/api/fines")).status()).toBe(200);
    expect((await writerApi.get("/api/submission-assignments")).status()).toBe(200);
    expect((await publicApi.get(`/api/public/${linkToken}/assignments`)).status()).toBe(200);
  } finally {
    await publicApi?.dispose().catch(() => {});
    // Immer mit allen Demo-Features zurücklassen - sonst brechen andere e2e-Specs, die auf
    // dem geteilten Demo-Mandanten Finanzen/Bussen/Abgabebox ansprechen.
    if (tenantId) {
      await adminApi.put(`/api/admin/tenants/${tenantId}/features`, { data: { enabled_codes: ALL_DEMO_FEATURES } }).catch(() => {});
    }
    await writerApi.dispose();
    await adminApi.dispose();
  }
});
