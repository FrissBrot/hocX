import { test, expect, request } from "@playwright/test";
import { authFiles, platformAdminPasskeyFile } from "./auth";
import { SoftPasskey, stepUpHeaders } from "./soft-passkey";
import { addVirtualAuthenticator } from "./webauthn";

// Plattform-Admins: nur Passwort + Passkey (backend admin_mfa_service.py, Migration 0205).
//
// WebAuthn braucht eine Domain statt einer IP: Chromium lehnt rp.id "127.0.0.1" ab, "localhost"
// akzeptiert es. Die Specs laufen deshalb auf "localhost" statt PLAYWRIGHT_BASE_URL (127.0.0.1);
// ohne Admin-Domain (E2E-Stack) leitet das Backend RP-ID und Origin aus dem Origin des Browsers ab.
const localhostBaseURL = (process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:13000").replace("127.0.0.1", "localhost");
const password = process.env.E2E_USER_PASSWORD ?? "ChangeMe123!";

test("neuer Admin: Passwort, Passkey einrichten (Pflicht), danach Login nur mit Passkey", async ({ browser }) => {
  // Admin anlegen braucht eine Passkey-Bestätigung (Review M2): mit dem Software-Passkey aus auth.setup.ts
  const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:13000";
  const origin = new URL(baseURL).origin;
  const owner = await request.newContext({ baseURL, storageState: authFiles.platformAdmin, extraHTTPHeaders: { Origin: origin } });
  const ownerPasskey = await SoftPasskey.load(platformAdminPasskeyFile);
  expect(ownerPasskey, "Software-Passkey aus auth.setup.ts fehlt").toBeTruthy();
  const email = `passkey-${Date.now()}@hocx.local`;
  const body = JSON.stringify({ email, display_name: "Passkey Test", password, role: "owner" });
  const unconfirmed = await owner.post("/api/admin/admins", { data: body, headers: { "Content-Type": "application/json" } });
  expect(unconfirmed.status()).toBe(403);
  const confirmHeaders = await stepUpHeaders(owner, ownerPasskey!, origin, "admin-manage", "POST", "/api/admin/admins", body);
  const created = await owner.post("/api/admin/admins", { data: body, headers: { "Content-Type": "application/json", ...confirmHeaders } });
  expect(created.ok(), await created.text()).toBeTruthy();
  await ownerPasskey!.save(platformAdminPasskeyFile);
  await owner.dispose();

  const context = await browser.newContext({ baseURL: localhostBaseURL });
  const page = await context.newPage();
  const removeAuthenticator = await addVirtualAuthenticator(page);
  try {
    // Ohne Passkey gibt es keine Session - auch nicht nach dem Passwort
    await page.goto("/admin/login");
    await page.getByLabel("E-Mail").fill(email);
    await page.getByLabel("Passwort").fill(password);
    await page.getByRole("button", { name: "Einloggen" }).click();
    await expect(page.getByText("Für Platform-Admin-Konten ist ein Passkey Pflicht")).toBeVisible();
    expect((await (await context.request.get("/api/admin/auth/session")).json()).authenticated).toBe(false);
    expect((await context.request.get("/api/admin/tenants")).status()).toBe(401);
    // Kein TOTP-Weg mehr
    await expect(page.getByText(/TOTP|Authenticator-App/)).toHaveCount(0);

    await page.getByRole("button", { name: "Passkey einrichten und anmelden" }).click();
    await page.waitForURL("**/admin");
    expect((await (await context.request.get("/api/admin/auth/session")).json()).authenticated).toBe(true);

    // Abmelden und erneut: jetzt Bestätigung mit dem vorhandenen Passkey
    await context.request.post("/api/admin/auth/logout");
    await page.goto("/admin/login");
    await page.getByLabel("E-Mail").fill(email);
    await page.getByLabel("Passwort").fill(password);
    await page.getByRole("button", { name: "Einloggen" }).click();
    await page.getByRole("button", { name: "Mit Passkey bestätigen" }).click();
    await page.waitForURL("**/admin");

    // Selbstverwaltung: der letzte Passkey ist nicht entfernbar, ein zweiter schon
    await page.goto("/admin/security");
    await expect(page.locator(".security-factor-card")).toHaveCount(1);
    await expect(page.locator(".security-factor-card").getByRole("button", { name: "Entfernen" })).toBeDisabled();
    const overview = await (await context.request.get("/api/admin/mfa")).json();
    // Ohne Passkey-Bestätigung lehnt der Server jede Änderung ab (Review M2)
    const unconfirmedDelete = await context.request.delete(`/api/admin/mfa/factors/${overview.factors[0].id}`);
    expect(unconfirmedDelete.status()).toBe(403);

    // Zweiter Schlüssel: derselbe virtuelle Authenticator lehnt einen zweiten Passkey für dasselbe
    // Konto ab (excludeCredentials) - wie im echten Leben ein zweites Gerät anstecken.
    const removeSecondKey = await addVirtualAuthenticator(page, "usb");
    await page.getByRole("button", { name: "Passkey hinzufügen" }).click();
    await expect(page.locator(".security-factor-card")).toHaveCount(2);
    await page.locator(".security-factor-card").first().getByRole("button", { name: "Entfernen" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Entfernen" }).click();
    await expect(page.locator(".security-factor-card")).toHaveCount(1);
    await removeSecondKey();
  } finally {
    await removeAuthenticator();
    await context.close();
  }
});
