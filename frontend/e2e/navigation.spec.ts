import { test, expect } from "@playwright/test";

test("protected pages redirect anonymous visitors", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("/todos");
  await expect(page).toHaveURL(/\/login/);
  await context.close();
});

test("main navigation pages can be opened", async ({ page }) => {
  for (const path of ["/", "/todos", "/events", "/participants", "/lists", "/users", "/templates", "/submission-assignments"]) {
    await page.goto(path);
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page.locator("body")).not.toBeEmpty();
  }
});
