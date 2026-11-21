import { test, expect } from "@playwright/test";
import { authFiles } from "./auth";

// Admin-Sidebar mit einklappbaren Bereichen (1.5.1): der Bereich der aktiven Seite ist offen, alle
// anderen zu - bei 1440×800 und 1440×700 scrollt die Sidebar dann nicht. Mit ADMIN_SHOTS_DIR
// entstehen dazu Screenshots (Light/Dark).
const PAGES = ["/admin", "/admin/tenants", "/admin/users", "/admin/security/events", "/admin/system", "/admin/analytics", "/admin/settings/notifications"];
const dir = process.env.ADMIN_SHOTS_DIR;

test.describe("Admin-Sidebar: Bereiche einklappen", () => {
  test.use({ storageState: authFiles.platformAdmin });
  test.setTimeout(300_000);

  for (const height of [800, 700]) {
    test(`aktiver Bereich offen, nichts scrollt (1440×${height})`, async ({ page }) => {
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
        const sizes = await page.evaluate(() => {
          const nav = document.querySelector(".admin-sidebar-nav") as HTMLElement;
          const aside = document.querySelector("aside.admin-sidebar") as HTMLElement;
          return { nav: [nav.scrollHeight, nav.clientHeight], aside: [aside.scrollHeight, aside.clientHeight] };
        });
        expect(sizes.nav[0], `${path} Navigation ${JSON.stringify(sizes)}`).toBeLessThanOrEqual(sizes.nav[1] + 1);
        expect(sizes.aside[0], `${path} Sidebar ${JSON.stringify(sizes)}`).toBeLessThanOrEqual(sizes.aside[1] + 1);
      }
    });
  }

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
