import { test, expect, type BrowserContext } from "@playwright/test";
import { authFiles } from "./auth";
import { addVirtualAuthenticator } from "./webauthn";

// Plattform-Admins: nur Passwort + Passkey (backend admin_mfa_service.py, Migration 0205).
//
// WebAuthn braucht eine Domain statt einer IP: Chromium lehnt rp.id "127.0.0.1" ab, "localhost"
// akzeptiert es. Die Specs laufen deshalb auf "localhost" statt PLAYWRIGHT_BASE_URL (127.0.0.1);
// ohne Admin-Domain (E2E-Stack) leitet das Backend RP-ID und Origin aus dem Origin des Browsers ab.
const localhostBaseURL = (process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:13000").replace("127.0.0.1", "localhost");
const password = process.env.E2E_USER_PASSWORD ?? "ChangeMe123!";

async function platformAdminApi(browser: import("@playwright/test").Browser): Promise<BrowserContext> {
  // Session des Plattform-Admins aus auth.setup.ts (Software-Passkey), auf localhost übertragen
  const seed = await browser.newContext({ storageState: authFiles.platformAdmin });
  const cookies = await seed.cookies();
  await seed.close();
  const context = await browser.newContext({ baseURL: localhostBaseURL });
  await context.addCookies(cookies.map((cookie) => ({ ...cookie, domain: "localhost" })));
  return context;
}

test("neuer Admin: Passwort, Passkey einrichten (Pflicht), danach Login nur mit Passkey", async ({ browser }) => {
  const owner = await platformAdminApi(browser);
  const email = `passkey-${Date.now()}@hocx.local`;
  const created = await owner.request.post("/api/admin/admins", {
    data: { email, display_name: "Passkey Test", password, role: "owner" },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  await owner.close();

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
    const lastDelete = await context.request.delete(`/api/admin/mfa/factors/${overview.factors[0].id}`);
    expect(lastDelete.status()).toBe(409);

    await page.getByRole("button", { name: "Passkey hinzufügen" }).click();
    await expect(page.locator(".security-factor-card")).toHaveCount(2);
    await page.locator(".security-factor-card").first().getByRole("button", { name: "Entfernen" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Entfernen" }).click();
    await expect(page.locator(".security-factor-card")).toHaveCount(1);
  } finally {
    await removeAuthenticator();
    await context.close();
  }
});
