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
  // Neun Seiten, die der Dev-Server des E2E-Stacks beim ersten Aufruf je erst kompiliert:
  // das 45-s-Standardlimit reichte auf einem ausgelasteten Host nicht immer (Timeout in page.goto).
  test.setTimeout(180_000);
  for (const path of ["/", "/my-tasks", "/todos", "/events", "/participants", "/lists", "/users", "/templates", "/submission-assignments"]) {
    await page.goto(path);
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page.locator("body")).not.toBeEmpty();
  }
});

test("mobile navigation closes when clicking outside the sidebar", async ({ page }) => {
  // Bis 900 px rendert die Mobile-Shell mit Tableiste (use-is-mobile.tsx), die einklappbare
  // Sidebar gibt es nur noch im Tablet-Bereich 901-1100 px (globals.css).
  await page.setViewportSize({ width: 1000, height: 800 });
  await page.goto("/todos");

  const sidebar = page.locator(".sidebar");
  await page.locator(".mobile-nav-toggle").click();
  await expect(sidebar).toHaveClass(/sidebar-open/);

  await page.locator(".sidebar-overlay").click({ position: { x: 500, y: 400 } });
  await expect(sidebar).not.toHaveClass(/sidebar-open/);
});

test("Zahnrad in der Kopfzeile führt vom Bereich zur Einstellung und zurück", async ({ page }) => {
  await page.goto("/todos");
  const related = page.locator(".topbar-related");
  await expect(related).toHaveAttribute("href", "/task-packages");
  await related.click();
  await expect(page).toHaveURL(/\/task-packages$/);
  // Auf der Einstellung: zurück zum Bereich (erste Seite der Gruppe «Aufgaben»)
  await expect(page.locator(".topbar-related")).toHaveAttribute("href", "/todos");
  // Die Einstellung steht nicht mehr in der Seitenleiste: Knopf «Einstellungen» ist aktiv, die
  // Unternavigation des Einstellungen-Rahmens markiert die Seite
  await expect(page.locator('.sidebar .nav-link[href="/task-packages"]')).toHaveCount(0);
  await expect(page.locator(".sidebar-settings-link")).toHaveClass(/nav-link-active/);
  await expect(page.locator('.settings-subnav-link-active[href="/task-packages"]')).toBeVisible();
});

test("Einstellungen: Knopf über der Benutzerkarte führt zur Übersicht mit Suche", async ({ page }) => {
  test.setTimeout(150_000); // zwei Erstkompilierungen à bis 60 s
  await page.goto("/todos");
  await page.locator(".sidebar-settings-link").click();
  // Erster Aufruf: der Next-Server des E2E-Stacks kompiliert /settings erst (unter Volllast und auf
  // dem GitHub-Runner > 30 s)
  await expect(page).toHaveURL(/\/settings$/, { timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "Einstellungen", level: 1 })).toBeVisible();
  await expect(page.locator('.settings-hub-card[href="/tenant-settings"]')).toBeVisible();
  await page.getByRole("textbox", { name: "Einstellung finden" }).fill("dsgvo");
  await expect(page.locator('.settings-hub-card[href="/tenant-settings/privacy"]')).toBeVisible();
  await expect(page.locator('.settings-hub-card[href="/tenant-settings"]')).toHaveCount(0);
  await page.locator('.settings-hub-card[href="/tenant-settings/privacy"]').click();
  await expect(page).toHaveURL(/\/tenant-settings\/privacy$/, { timeout: 60_000 });
  await expect(page.locator(".topbar-breadcrumb")).toContainText("Einstellungen");
  await expect(page.locator(".topbar-breadcrumb")).toContainText("Datenschutz");
});

test("Meine Aufgaben verlinkt auf alle Pendenzen", async ({ page }) => {
  await page.goto("/my-tasks");
  await expect(page.getByRole("heading", { name: "Meine Aufgaben", level: 1 })).toBeVisible();
  await page.getByRole("link", { name: "Alle Pendenzen →" }).click();
  await expect(page).toHaveURL(/\/todos$/);
});
