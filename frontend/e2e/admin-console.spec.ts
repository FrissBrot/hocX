import { test, expect, type Page } from "@playwright/test";
import { authFiles } from "./auth";

// Admin-Redesign (Plan /admin-redesign, Phasen B–F): Konsole mit Navigation A–G, Ctrl+K,
// Dashboard, Mandanten-Detail, Sicherheitsbereich und die Warnungsansicht für Vereins-Admins.

const ADMIN_PAGES = [
  "/admin",
  "/admin/tenants",
  "/admin/verifications",
  "/admin/domains",
  "/admin/plans",
  "/admin/cashflow",
  "/admin/users",
  "/admin/admins",
  "/admin/security",
  "/admin/security/events",
  "/admin/security/blocks",
  "/admin/security/alerts",
  "/admin/security/audit",
  "/admin/security/policy",
  "/admin/system",
  "/admin/jobs",
  "/admin/error-logs",
  "/admin/upload-pipeline",
  "/admin/operations/delivery",
  "/admin/storage",
  "/admin/backups",
  "/admin/maintenance",
  "/admin/analytics",
  "/admin/settings/notifications",
  "/admin/document-templates",
  "/admin/account",
];

async function expectHealthyPage(page: Page, path: string) {
  const response = await page.goto(path);
  expect(response?.status(), path).toBeLessThan(400);
  await expect(page.locator("main#main-content"), path).toBeVisible();
  await expect(page.getByText(/Application error|MISSING_MESSAGE/), path).toHaveCount(0);
}

test.describe("Admin-Konsole", () => {
  test.use({ storageState: authFiles.platformAdmin });

  test("alle Bereiche laden in der gemeinsamen Shell, alte URLs leiten um", async ({ page }) => {
    for (const path of ADMIN_PAGES) await expectHealthyPage(page, path);

    const nav = page.getByRole("navigation", { name: "Admin-Navigation" });
    for (const group of ["Mandanten", "Benutzer & Zugänge", "Sicherheit", "Betrieb", "Analysen", "Einstellungen"]) {
      await expect(nav.getByText(group, { exact: true }).first()).toBeVisible();
    }

    await page.goto("/admin/audit");
    await expect(page).toHaveURL(/\/admin\/security\/audit$/);
    await page.goto("/admin/notifications");
    await expect(page).toHaveURL(/\/admin\/settings\/notifications$/);
  });

  test("Ctrl+K findet Seiten und Mandanten und navigiert per Tastatur", async ({ page }) => {
    await page.goto("/admin");
    await page.locator("main#main-content").focus();
    await page.keyboard.press("ControlOrMeta+K");
    const input = page.getByRole("combobox", { name: "Admin durchsuchen" });
    await expect(input).toBeFocused();
    await input.fill("jobs");
    await expect(page.getByRole("option", { name: /Jobs/ }).first()).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/admin\/jobs$/);

    // Mandant über die Server-Suche (POST /api/admin/search)
    const tenants = await (await page.request.get("/api/admin/tenants?limit=1&offset=0")).json();
    const tenant = tenants.items[0] as { id: string; name: string };
    await page.keyboard.press("ControlOrMeta+K");
    await input.fill(tenant.name.slice(0, 6));
    const option = page.getByRole("listbox").getByRole("option").filter({ hasText: tenant.name.slice(0, 6) }).first();
    await expect(option).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(input).toHaveCount(0);
  });

  test("Dashboard zeigt Status, Kennzahlen und lädt keine Benutzerlisten", async ({ page }) => {
    const userListCalls: string[] = [];
    page.on("request", (request) => {
      if (/\/api\/admin\/users(\?|$)/.test(request.url())) userListCalls.push(request.url());
    });
    await expectHealthyPage(page, "/admin");
    const overview = await page.request.get("/api/admin/overview");
    expect(overview.ok()).toBeTruthy();
    expect(JSON.stringify(await overview.json())).not.toMatch(/@hocx\.(local|invalid)/);
    expect(userListCalls).toEqual([]);
  });

  test("Mandanten-Detail: Liste führt auf die Detailseite mit Tabs", async ({ page }) => {
    const tenants = await (await page.request.get("/api/admin/tenants?limit=1&offset=0")).json();
    const tenant = tenants.items[0] as { id: string; name: string };
    await page.goto("/admin/tenants");
    await page.getByRole("link", { name: tenant.name, exact: true }).first().click();
    await expect(page).toHaveURL(new RegExp(`/admin/tenants/${tenant.id}`));
    const tabs = page.getByRole("tablist");
    for (const tab of ["Stammdaten", "Speicher", "Domains"]) {
      await tabs.getByRole("tab", { name: tab }).click();
      await expect(page.locator("main#main-content")).toBeVisible();
      await expect(page.getByText(/Application error|MISSING_MESSAGE/)).toHaveCount(0);
    }
    // Fremde/unbekannte ID: 404
    const missing = await page.goto("/admin/tenants/00000000-0000-4000-8000-000000000000");
    expect(missing?.status()).toBe(404);
  });

  test("Sicherheits-Dashboard liest nur Pseudonyme, Richtlinien ohne Geheimnisse", async ({ page }) => {
    await expectHealthyPage(page, "/admin/security");
    const policy = await page.request.get("/api/admin/auth-security/policy");
    expect(policy.ok()).toBeTruthy();
    const body = JSON.stringify(await policy.json()).toLowerCase();
    expect(body).not.toMatch(/"[^"]*(secret|password|token)[^"]*":\s*"[^"]{8,}"/);
  });
});

test.describe("Sicherheit & Anmeldungen (Verein)", () => {
  test("Vereins-Admin mit security.read sieht die Warnungsansicht", async ({ browser }) => {
    const context = await browser.newContext({ storageState: authFiles.admin });
    const page = await context.newPage();
    try {
      await expectHealthyPage(page, "/tenant-settings/security");
      const api = await page.request.get("/api/auth-security/activity");
      expect(api.status()).toBe(200);
      expect(JSON.stringify(await api.json())).not.toMatch(/"(ip|src_ip|src_net_hash|ip_hash)"/);
    } finally {
      await context.close();
    }
  });

  test("ohne security.read (Schreiberin) kein Zugriff", async ({ browser }) => {
    const context = await browser.newContext({ storageState: authFiles.writer });
    const page = await context.newPage();
    try {
      const api = await page.request.get("/api/auth-security/activity");
      expect(api.status()).toBe(403);
      await page.goto("/tenant-settings/security");
      await expect(page.getByRole("navigation").getByRole("link", { name: "Sicherheit & Anmeldungen" })).toHaveCount(0);
    } finally {
      await context.close();
    }
  });
});
