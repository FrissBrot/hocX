import AxeBuilder from "@axe-core/playwright";
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
  "/admin/settings/security",
  "/admin/settings/integrations",
  "/admin/settings/system",
  "/admin/document-templates",
  "/admin/account",
];

async function expectHealthyPage(page: Page, path: string) {
  // ERR_ABORTED: eine Client-Navigation der vorigen Seite (z. B. Polling/Redirect) bricht den Aufruf ab - einmal wiederholen
  const response = await page.goto(path).catch(() => page.goto(path));
  expect(response?.status(), path).toBeLessThan(400);
  await expect(page.locator("main#main-content"), path).toBeVisible();
  await expect(page.getByText(/Application error|MISSING_MESSAGE/), path).toHaveCount(0);
}

test.describe("Admin-Konsole", () => {
  test.use({ storageState: authFiles.platformAdmin });
  // Dev-Server des E2E-Stacks kompiliert jede Route beim ersten Aufruf
  test.setTimeout(240_000);

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
    await expect(page).toHaveURL(new RegExp(`/admin/tenants/${tenant.id}`), { timeout: 60_000 });
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

  test("Mandanten-Detail 1.5.1: Features, Nutzung und Sicherheit", async ({ page }) => {
    const tenants = await (await page.request.get("/api/admin/tenants?limit=1&offset=0")).json();
    const tenant = tenants.items[0] as { id: string };
    for (const segment of ["features", "usage", "security"]) await expectHealthyPage(page, `/admin/tenants/${tenant.id}/${segment}`);
    await expect(page.getByRole("tab", { name: "Sicherheit" })).toHaveAttribute("aria-selected", "true");
  });

  test("Audit-Log: Filter stehen nur mit IDs/Codes in der URL", async ({ page }) => {
    await expectHealthyPage(page, "/admin/security/audit?outcome=failure&actor_kind=system&from=2026-01-01");
    await expect(page.getByRole("tab", { name: "Fehlgeschlagen" })).toHaveAttribute("aria-selected", "true");
    await page.getByPlaceholder("Aktion, z. B. user.login").fill("admin.login");
    await expect(page).toHaveURL(/action=admin\.login/);
    expect(page.url()).not.toMatch(/%40|@/);
  });

  test("Audit-Log (Design): Bereiche, Zeitleiste, J/K-Detail und Link zum Eintrag", async ({ page }) => {
    await expectHealthyPage(page, "/admin/security/audit?range=30d");
    await expect(page.getByText("Das Ansehen dieser Seite wird protokolliert")).toBeVisible();
    await expect(page.getByRole("img", { name: "Zeitleiste der Ereignisse" })).toBeVisible();
    const firstRow = page.locator("tr.audit-row").first();
    await expect(firstRow).toBeVisible();
    await page.locator("main#main-content").focus();
    await page.keyboard.press("j");
    const detail = page.locator("aside.audit-detail");
    await expect(detail).toBeVisible();
    await expect(page).toHaveURL(/entry=\d+/);
    const entryId = /entry=(\d+)/.exec(page.url())?.[1];
    await page.keyboard.press("j");
    await expect(page).not.toHaveURL(new RegExp(`entry=${entryId}(&|$)`));
    await page.keyboard.press("k");
    await expect(page).toHaveURL(new RegExp(`entry=${entryId}(&|$)`));
    // Link zum Eintrag: öffnet direkt die Detail-Spalte
    await expectHealthyPage(page, `/admin/security/audit?entry=${entryId}`);
    await expect(page.locator("aside.audit-detail")).toBeVisible();
    // Bereichs-Chip als Code in der URL
    await page.getByRole("button", { name: /^Anmeldung/ }).click();
    await expect(page).toHaveURL(/area=auth/);
    expect(page.url()).not.toMatch(/%40|@/);
    // 390 px: die Seite wird nicht breiter als der Viewport (Tabelle und Reiter scrollen in sich)
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/admin/security/audit?range=30d");
    await expect(page.locator("tr.audit-row").first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
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

// Smartphone (390 px): keine Admin-Seite wird breiter als der Viewport - breite Tabellen, Reiter und
// Diagramme scrollen bzw. schrumpfen in sich.
test.describe("Admin-Konsole: 390 px ohne horizontales Überlaufen", () => {
  test.use({ storageState: authFiles.platformAdmin, viewport: { width: 390, height: 844 } });
  test.setTimeout(480_000);

  test("alle Admin-Seiten passen in 390 px", async ({ page }) => {
    const tenants = await (await page.request.get("/api/admin/tenants?limit=1&offset=0")).json();
    const tenantId = tenants.items?.[0]?.id as string | undefined;
    const tenantTabs = ["", "/profile", "/subscription", "/features", "/users", "/domains", "/verification", "/storage", "/usage", "/activity", "/security", "/technical"];
    const pages = tenantId ? [...ADMIN_PAGES, ...tenantTabs.map((tab) => `/admin/tenants/${tenantId}${tab}`)] : ADMIN_PAGES;
    const tooWide: string[] = [];
    for (const path of pages) {
      await expectHealthyPage(page, path);
      await page.waitForLoadState("networkidle").catch(() => undefined);
      const width = await page.evaluate(() => document.documentElement.scrollWidth);
      if (width > 391) tooWide.push(`${path}: ${width}px`);
    }
    expect(tooWide, tooWide.join("\n")).toEqual([]);
  });
});

// WCAG-Prüfung der Admin-Konsole (Plan Phase F): axe-core auf allen Bereichen, Regeln WCAG 2.1 A/AA.
// Bekannte, bewusst offene Punkte stehen mit Begründung in AXE_DISABLED.
const AXE_DISABLED: string[] = [
  // Breite Tabellen scrollen auf schmalen Viewports in .table-shell; jede Zeile hat einen fokussierbaren
  // Link/Knopf, der den Bereich per Tastatur mitscrollt. Ein tabIndex auf jedem Tabellen-Container
  // würde überall zusätzliche Tab-Halte erzeugen - offen für eine eigene Entscheidung.
  "scrollable-region-focusable",
];

test.describe("Admin-Konsole: Barrierefreiheit (axe)", () => {
  test.use({ storageState: authFiles.platformAdmin });
  test.setTimeout(480_000);

  test("keine WCAG-A/AA-Verstösse auf den Admin-Seiten", async ({ page }) => {
    const tenants = await (await page.request.get("/api/admin/tenants?limit=1&offset=0")).json();
    const tenantId = tenants.items?.[0]?.id as string | undefined;
    const pages = tenantId ? [...ADMIN_PAGES, `/admin/tenants/${tenantId}`, `/admin/tenants/${tenantId}/usage`, `/admin/tenants/${tenantId}/features`] : ADMIN_PAGES;
    const findings: string[] = [];
    for (const path of pages) {
      await expectHealthyPage(page, path);
      await page.waitForLoadState("networkidle").catch(() => undefined);
      const result = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .disableRules(AXE_DISABLED)
        .analyze();
      for (const violation of result.violations) {
        findings.push(`${path}: ${violation.id} (${violation.impact}) – ${violation.nodes.slice(0, 3).map((node) => node.target.join(" ")).join(" | ")}`);
      }
    }
    expect(findings, findings.join("\n")).toEqual([]);
  });
});
