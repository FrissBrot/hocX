import { test, expect } from "@playwright/test";
import { authFiles } from "./auth";

// Admin-Sidebar mit einklappbaren Bereichen (1.5.1): der Bereich der aktiven Seite ist offen, alle
// anderen zu. Seit 1.5.2 hat sie die Abstände der App-Sidebar (Einträge 40 px): grosse Bereiche
// scrollen innerhalb der Navigation, der aktive Eintrag bleibt sichtbar und die Sidebar selbst läuft
// nicht über. Mit ADMIN_SHOTS_DIR entstehen dazu Screenshots (Light/Dark).
const PAGES = ["/admin", "/admin/tenants", "/admin/users", "/admin/security/events", "/admin/system", "/admin/analytics", "/admin/settings/notifications"];
const dir = process.env.ADMIN_SHOTS_DIR;

test.describe("Admin-Sidebar: Bereiche einklappen", () => {
  test.use({ storageState: authFiles.platformAdmin });
  test.setTimeout(300_000);

  for (const height of [800, 700]) {
    test(`aktiver Bereich offen, aktiver Eintrag sichtbar (1440×${height})`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height });
      for (const path of PAGES) {
        await page.goto(path);
        const sidebar = page.locator("aside.admin-sidebar");
        await expect(sidebar).toBeVisible();
        const toggles = sidebar.locator("button.admin-nav-group-title");
        await expect(toggles.first()).toBeVisible();
        const open = sidebar.locator('button.admin-nav-group-title[aria-expanded="true"]');
        if (path !== "/admin") await expect(open, path).toHaveCount(1);
        expect(await open.count(), path).toBeLessThanOrEqual(1);
        await expect(sidebar.locator(".nav-link-active")).toHaveCount(1);
        await expect
          .poll(() =>
            page.evaluate(() => {
              const nav = (document.querySelector(".admin-sidebar-nav") as HTMLElement).getBoundingClientRect();
              const active = (document.querySelector(".admin-sidebar .nav-link-active") as HTMLElement).getBoundingClientRect();
              return active.top >= nav.top - 1 && active.bottom <= nav.bottom + 1;
            }),
          { message: `${path}: aktiver Eintrag im sichtbaren Teil der Navigation` })
          .toBe(true);
        const aside = await page.evaluate(() => {
          const element = document.querySelector("aside.admin-sidebar") as HTMLElement;
          return [element.scrollHeight, element.clientHeight];
        });
        expect(aside[0], `${path} Sidebar ${JSON.stringify(aside)}`).toBeLessThanOrEqual(aside[1] + 1);
      }
    });
  }

  test("Titel «hocX Konsole» und eigenes Favicon (1.5.2)", async ({ page, browser }) => {
    await page.goto("/admin/tenants");
    await expect(page).toHaveTitle("hocX Konsole");
    await expect(page.locator("aside.admin-sidebar h2.sidebar-title")).toHaveText("hocX Konsole");
    await expect(page.locator('link[rel="icon"][href="/icons/console/icon.svg"]')).toHaveCount(1);
    await expect(page.locator('link[rel="icon"][href^="/favicon.ico"]')).toHaveCount(0);
    expect((await page.request.get("/icons/console/favicon.ico")).headers()["content-type"]).toContain("image/");

    // Login der Konsole (ohne Sitzung) und die App behalten bzw. bekommen ihren Titel und ihr Icon
    const anonymous = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    const login = await anonymous.newPage();
    await login.goto("/admin/login");
    await expect(login).toHaveTitle("hocX Konsole");
    await expect(login.getByText("hocX Konsole", { exact: true })).toBeVisible();
    await login.goto("/login");
    await expect(login).toHaveTitle("hocX");
    await expect(login.locator('link[rel="icon"][href^="/favicon.ico"]')).toHaveCount(1);
    await anonymous.close();
  });

  test("Tastatur: Enter/Leertaste klappt einen Bereich auf und zu, Ctrl+K bleibt", async ({ page }) => {
    await page.goto("/admin/tenants");
    const toggle = page.locator("aside.admin-sidebar").getByRole("button", { name: /Betrieb/ });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.focus();
    await page.keyboard.press("Enter");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    const list = page.locator(`#${await toggle.getAttribute("aria-controls")}`);
    await expect(list.getByRole("link", { name: "Jobs" })).toBeVisible();
    await page.keyboard.press(" ");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await page.keyboard.press("ControlOrMeta+K");
    await expect(page.getByRole("combobox", { name: "Admin durchsuchen" })).toBeFocused();
  });

  test("Screenshots Sidebar (Light/Dark, 1440×700/800)", async ({ browser }) => {
    test.skip(!dir, "nur mit ADMIN_SHOTS_DIR");
    for (const scheme of ["light", "dark"] as const) {
      for (const height of [800, 700]) {
        const context = await browser.newContext({ storageState: authFiles.platformAdmin, colorScheme: scheme, viewport: { width: 1440, height } });
        const page = await context.newPage();
        for (const path of ["/admin/system", "/admin/security/events"]) {
          await page.goto(path);
          await page.waitForLoadState("networkidle").catch(() => undefined);
          await page.screenshot({ path: `${dir}/sidebar${path.replace(/\//g, "_")}-${scheme}-1440x${height}.png` });
        }
        await context.close();
      }
    }
  });
});
