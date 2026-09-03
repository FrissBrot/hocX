import { test, expect } from "@playwright/test";

test("protected pages redirect anonymous visitors", async ({ browser }) => {
  // storageState: undefined is required, not just the default - the "chromium" project
  // (playwright.config.ts) sets `use.storageState: "e2e/.auth/admin.json"` for its normal
  // page/context fixtures, and browser.newContext() picks that project default up too
  // unless explicitly overridden. Without this, "anonymous" was silently the logged-in
  // admin the whole time (confirmed by dumping context.cookies() right after newContext(),
  // before any navigation: the session cookie was already there) - the redirect never
  // firing had nothing to do with app-shell.tsx at all.
  const context = await browser.newContext({ storageState: undefined });
  const page = await context.newPage();
  await page.goto("/todos");
  // The dev server (next dev/Turbopack - there's no separate production-build path in this
  // stack) compiles each route on its first visit, which can take a few seconds; a modest
  // bump over the 5s expect default absorbs a cold /todos without masking a real failure.
  await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
  await context.close();
});

test("main navigation pages can be opened", async ({ page }) => {
  for (const path of ["/", "/todos", "/events", "/participants", "/lists", "/users", "/templates", "/submission-assignments"]) {
    await page.goto(path);
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page.locator("body")).not.toBeEmpty();
  }
});

test("mobile navigation closes when clicking outside the sidebar", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 800 });
  await page.goto("/todos");

  const sidebar = page.locator(".sidebar");
  await page.locator(".mobile-nav-toggle").click();
  await expect(sidebar).toHaveClass(/sidebar-open/);

  await page.locator(".sidebar-overlay").click({ position: { x: 500, y: 400 } });
  await expect(sidebar).not.toHaveClass(/sidebar-open/);
});
