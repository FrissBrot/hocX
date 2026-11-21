import { test, type Browser } from "@playwright/test";
import { authFiles } from "./auth";

// Screenshots der Admin-Konsole (Light/Dark × 1440/390) für die Sichtprüfung gegen die Wireframes.
// Läuft nur mit ADMIN_SHOTS_DIR (kein Teil des normalen E2E-Laufs).
const dir = process.env.ADMIN_SHOTS_DIR;

const ADMIN_PAGES = [
  "/admin", "/admin/tenants", "/admin/security", "/admin/analytics", "/admin/system", "/admin/security/events", "/admin/account",
  // 1.5.1
  "/admin/security/audit", "/admin/security/alerts", "/admin/users", "/admin/admins", "/admin/storage", "/admin/error-logs",
  "/admin/settings/security", "/admin/settings/integrations", "/admin/settings/system",
];

async function shoot(browser: Browser, storageState: string, paths: string[], prefix: string) {
  for (const scheme of ["light", "dark"] as const) {
    for (const width of [1440, 390]) {
      const context = await browser.newContext({ storageState, colorScheme: scheme, viewport: { width, height: width > 600 ? 900 : 844 } });
      const page = await context.newPage();
      for (const path of paths) {
        await page.goto(path);
        await page.waitForLoadState("networkidle").catch(() => undefined);
        const name = `${prefix}${path.replace(/\//g, "_") || "_root"}-${scheme}-${width}.png`;
        await page.screenshot({ path: `${dir}/${name}`, fullPage: true });
      }
      await context.close();
    }
  }
}

test.describe("Admin-Screenshots", () => {
  test.skip(!dir, "nur mit ADMIN_SHOTS_DIR");
  test.setTimeout(240_000);

  test("Admin-Hauptseiten", async ({ browser }) => {
    const context = await browser.newContext({ storageState: authFiles.platformAdmin });
    const tenants = await (await context.request.get("/api/admin/tenants?limit=1&offset=0")).json();
    await context.close();
    const tenantId = tenants.items?.[0]?.id as string | undefined;
    await shoot(browser, authFiles.platformAdmin, tenantId ? [...ADMIN_PAGES, `/admin/tenants/${tenantId}`, `/admin/tenants/${tenantId}/features`, `/admin/tenants/${tenantId}/usage`, `/admin/tenants/${tenantId}/security`] : ADMIN_PAGES, "admin");
  });

  test("Audit-Log (Design 1.5.1): Liste und Detail", async ({ browser }) => {
    for (const scheme of ["light", "dark"] as const) {
      for (const width of [1440, 390]) {
        const context = await browser.newContext({ storageState: authFiles.platformAdmin, colorScheme: scheme, viewport: { width, height: width > 600 ? 900 : 844 } });
        const page = await context.newPage();
        await page.goto("/admin/security/audit?range=30d");
        await page.waitForLoadState("networkidle").catch(() => undefined);
        await page.screenshot({ path: `${dir}/audit-list-${scheme}-${width}.png`, fullPage: true });
        await page.locator("main#main-content").focus();
        await page.keyboard.press("j");
        await page.locator("aside.audit-detail").waitFor();
        await page.waitForLoadState("networkidle").catch(() => undefined);
        await page.screenshot({ path: `${dir}/audit-detail-${scheme}-${width}.png`, fullPage: true });
        await context.close();
      }
    }
  });

  test("Vereinsseite Sicherheit & Anmeldungen", async ({ browser }) => {
    await shoot(browser, authFiles.admin, ["/tenant-settings/security"], "tenant");
  });
});
