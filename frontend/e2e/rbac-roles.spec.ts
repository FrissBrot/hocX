import { test, expect, request as playwrightRequest } from "@playwright/test";
import { authFiles } from "./auth";

// Rollen und Berechtigungen (RBAC, docs/RBAC_ARCHITECTURE_PROPOSAL.md): eine eigene Rolle anlegen,
// einem neuen Konto zuweisen, mit diesem Konto prüfen - und ein Rechteentzug wirkt in der
// bestehenden Session sofort, ohne neues Login.

type Role = { id: string; name: string | null; system_key: string | null; permissions: string[]; locked: boolean };

test("eigene Rolle anlegen, zuweisen und wieder entziehen", async () => {
  const admin = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.admin });
  const suffix = Date.now();
  const roles: Role[] = await (await admin.get("/api/roles")).json();
  expect(roles.filter((role) => role.system_key).map((role) => role.system_key).sort()).toEqual(["admin", "kassier", "reader", "writer"]);
  expect(roles.find((role) => role.system_key === "admin")?.locked).toBe(true);

  const created = await admin.post("/api/roles", { data: { name: `E2E Kasse ${suffix}`, permissions: ["meetings.read", "finances.read"] } });
  expect(created.status(), await created.text()).toBe(201);
  const role: Role = await created.json();

  const password = `E2E-Rolle-${suffix}-Passwort`;
  const email = `rbac-${suffix}@example.invalid`;
  const userResponse = await admin.post("/api/users", {
    data: { first_name: "Rollen", last_name: "Test", display_name: `Rollen Test ${suffix}`, email, password, login_enabled: true, role_ids: [role.id] },
  });
  expect(userResponse.status(), await userResponse.text()).toBe(201);
  const user = await userResponse.json();
  expect(user.roles.map((entry: Role) => entry.id)).toEqual([role.id]);

  const member = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL });
  try {
    expect((await member.post("/api/auth/login", { data: { email, password } })).ok()).toBeTruthy();
    const session = await (await member.get("/api/auth/session")).json();
    expect(session.permissions.sort()).toEqual(["finances.read", "meetings.read"]);
    expect((await member.get("/api/protocols")).ok()).toBeTruthy();
    expect((await member.post("/api/todos", { data: { task: "nicht erlaubt" } })).status()).toBe(403);
    expect((await member.get("/api/users")).status()).toBe(403);
    expect((await member.get("/api/roles")).status()).toBe(403);

    // Rolle ändern: ohne meetings.read sieht dieselbe Session sofort keine Protokolle mehr.
    const changed = await admin.patch(`/api/roles/${role.id}`, { data: { permissions: ["finances.read"] } });
    expect(changed.ok(), await changed.text()).toBeTruthy();
    expect((await member.get("/api/protocols")).status()).toBe(403);
  } finally {
    await member.dispose();
    await admin.delete(`/api/users/${user.id}`);
    expect((await admin.delete(`/api/roles/${role.id}`)).status()).toBe(204);
    await admin.dispose();
  }
});

test("Schutzregeln: Standardrollen bleiben, fremde Rollen-IDs und eigene Herabstufung scheitern", async () => {
  const admin = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.admin });
  const roles: Role[] = await (await admin.get("/api/roles")).json();
  const adminRole = roles.find((role) => role.system_key === "admin");
  const readerRole = roles.find((role) => role.system_key === "reader");
  expect(adminRole && readerRole).toBeTruthy();

  expect((await admin.delete(`/api/roles/${readerRole!.id}`)).status()).toBe(409);
  expect((await admin.patch(`/api/roles/${adminRole!.id}`, { data: { name: "Chef" } })).status()).toBe(409);

  const session = await (await admin.get("/api/auth/session")).json();
  // Selbstentzug der Benutzerverwaltung (bzw. letzter Admin) wird abgelehnt.
  expect((await admin.put(`/api/users/${session.user.id}/roles`, { data: { role_ids: [readerRole!.id] } })).status()).toBe(409);
  // Unbekannte bzw. fremde Rollen-ID
  expect((await admin.put(`/api/users/${session.user.id}/roles`, { data: { role_ids: ["00000000-0000-7000-8000-000000000000"] } })).status()).toBe(400);
  await admin.dispose();
});

test("Leser sehen die Rollenverwaltung nicht", async () => {
  const reader = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.reader });
  expect((await reader.get("/api/roles")).status()).toBe(403);
  expect((await reader.post("/api/roles", { data: { name: "Hack", permissions: ["access.manage"] } })).status()).toBe(403);
  await reader.dispose();
});

test("Rollen-Seite zeigt Standardrollen und das Berechtigungsformular", async ({ browser }) => {
  const context = await browser.newContext({ storageState: authFiles.admin });
  const page = await context.newPage();
  await page.goto("/users/roles");
  await expect(page.locator(".data-table")).toBeVisible();
  await expect(page.locator(".roles-table-name").first()).toBeVisible();
  await page.locator(".page-header .button-primary").click();
  await expect(page.locator(".roles-permission-area").first()).toBeVisible();
  expect(await page.locator(".roles-permission-option").count()).toBeGreaterThanOrEqual(15);
  await context.close();
});
