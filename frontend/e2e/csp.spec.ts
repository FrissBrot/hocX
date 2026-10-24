import { expect, test, type Browser, type Page } from "@playwright/test";
import { authFiles } from "./auth";

// Nonce-CSP (Audit MAIN-FE-013): script-src ohne 'unsafe-inline'. Jede Seite muss ohne
// CSP-Verletzung laden, und die beiden Inline-Skripte aus app/layout.tsx (Laufzeit-Konfiguration,
// Theme vor dem ersten Paint) müssen mit ihrer Nonce tatsächlich laufen.

const tenantRoutes = [
  "/", "/connections", "/cycles", "/elements", "/events", "/files", "/finances", "/fines", "/lists",
  "/participants", "/photos", "/protocols", "/settings", "/shared-links", "/statistics",
  "/submission-assignments", "/task-packages", "/templates", "/tenant-settings", "/tenant-settings/abo",
  "/tenant-settings/domains", "/todos", "/tools", "/tools/import", "/tools/word-import", "/users",
];
const platformAdminRoutes = [
  "/admin", "/admin/admins", "/admin/domains", "/admin/error-logs", "/admin/jobs", "/admin/notifications",
  "/admin/plans", "/admin/security", "/admin/sso", "/admin/system", "/admin/tenants", "/admin/upload-pipeline",
  "/admin/users",
];
const publicRoutes = ["/login", "/admin/login", "/website", "/auth/bridge#token=ungueltig", "/share/ungueltig"];

async function collectViolations(page: Page): Promise<string[]> {
  const violations: string[] = [];
  page.on("console", (message) => {
    if (/Content Security Policy|Refused to (execute|load)/i.test(message.text())) violations.push(message.text());
  });
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (event) => {
      (window as unknown as { __cspViolations: string[] }).__cspViolations ??= [];
      (window as unknown as { __cspViolations: string[] }).__cspViolations.push(`${event.violatedDirective}: ${event.blockedURI}`);
    });
  });
  return violations;
}

async function expectCleanPage(page: Page, violations: string[], path: string) {
  const response = await page.goto(path, { waitUntil: "networkidle" });
  expect(response?.headers()["content-security-policy"], path).toContain("'strict-dynamic'");
  const state = await page.evaluate(() => ({
    config: typeof (window as unknown as { __HOCX_CONFIG__?: unknown }).__HOCX_CONFIG__ === "object",
    theme: document.documentElement.dataset.theme ?? null,
    violations: (window as unknown as { __cspViolations?: string[] }).__cspViolations ?? [],
  }));
  expect(state.config, `${path}: Laufzeit-Konfiguration (Inline-Skript mit Nonce) lief nicht`).toBe(true);
  expect(state.theme, `${path}: Theme-Skript (Inline-Skript mit Nonce) lief nicht`).not.toBeNull();
  expect([...violations, ...state.violations], path).toEqual([]);
}

async function checkRoutes(browser: Browser, storageState: string | undefined, routes: string[]) {
  const context = await browser.newContext({ storageState });
  const page = await context.newPage();
  const violations = await collectViolations(page);
  for (const path of routes) {
    await expectCleanPage(page, violations, path);
  }
  await context.close();
}

test("Mandanten-Seiten laden ohne CSP-Verletzung", async ({ browser, request }) => {
  test.setTimeout(240_000);
  const protocols = await (await request.get("/api/protocols?limit=1")).json();
  const templates = await (await request.get("/api/templates")).json();
  const dynamicRoutes = [
    ...(protocols.items?.[0]?.id ?? protocols[0]?.id ? [`/protocols/${protocols.items?.[0]?.id ?? protocols[0].id}`] : []),
    ...(templates[0]?.id ? [`/templates/${templates[0].id}`] : []),
  ];
  await checkRoutes(browser, authFiles.admin, [...tenantRoutes, ...dynamicRoutes]);
});

test("Plattform-Admin-Seiten laden ohne CSP-Verletzung", async ({ browser }) => {
  test.setTimeout(180_000);
  await checkRoutes(browser, authFiles.platformAdmin, platformAdminRoutes);
});

test("Öffentliche Seiten laden ohne CSP-Verletzung", async ({ browser }) => {
  await checkRoutes(browser, undefined, publicRoutes);
});
