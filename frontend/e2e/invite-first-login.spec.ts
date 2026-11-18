import { expect, test, type Page, type Route } from "@playwright/test";

// Erstlogin über eine Einladung (/auth/set-password, Design «hocX Erstlogin Einladung»):
// Passwort → zweiter Faktor → Fertig, plus die Zustände «Einladung ungültig» und «Kurz gesperrt».
//
// Das Einladungs-Token existiert nur in der Mail (im E2E-Stack gibt es keinen Mail-Empfang), daher
// beantwortet diese Spec die /api/auth/…-Aufrufe der Seite selbst. Den echten Ablauf im Backend
// (Einmal-Token, keine Session vor dem Faktor, Überspringen bei Pflicht abgelehnt, Session danach)
// prüft backend/tests/test_invite_first_login.py. Hier geht es um Seite, Zustände und Optik:
// Screenshots Light/Dark bei 1440 und 390 px unter test-results/invite-*.png.

const PASSWORD = "Tanne-Kiesel-Wolke-7";
const SECRET = "JBSWY3DPEHPK3PXP";

type Options = { required?: boolean; preview?: "ok" | "invalid" | "locked" };

async function mockApi(page: Page, { required = false, preview = "ok" }: Options = {}) {
  const json = (route: Route, status: number, body: unknown) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/auth/account-link/preview", (route) => {
    if (preview === "invalid") return json(route, 404, { detail: { code: "link_invalid", message: "Der Link ist ungültig oder abgelaufen." } });
    if (preview === "locked") return json(route, 429, { detail: { code: "rate_limited", message: "Too many requests" } });
    return json(route, 200, { purpose: "invite", display_name: "Ben Beispiel", email: "ben@beispiel.ch", tenant_name: "Musterverein Seeland" });
  });
  await page.route("**/api/auth/account-link/complete", (route) =>
    json(route, 200, {
      purpose: "invite",
      mfa_required: required,
      mfa: {
        status: "setup_required", ticket: "e2e-ticket", required, user_display_name: "Ben Beispiel", user_email: "ben@beispiel.ch",
        tenant_name: "Musterverein Seeland", available_methods: [], default_factor_type: null, default_factor_label: null,
        can_add_totp: true, can_add_passkey: true, can_skip: !required,
      },
    }));
  await page.route("**/api/auth/mfa/totp/setup/start", (route) =>
    json(route, 200, {
      flow_token: "e2e-flow", secret: SECRET, manual_entry_key: SECRET, issuer: "hocX", account_name: "ben@beispiel.ch",
      provisioning_uri: `otpauth://totp/hocX:ben%40beispiel.ch?secret=${SECRET}&issuer=hocX`,
    }));
  const loggedIn = { authenticated: true, bridge_redirect_url: null, mfa: null };
  await page.route("**/api/auth/mfa/totp/setup/complete", (route) => json(route, 200, loggedIn));
  await page.route("**/api/auth/mfa/setup/skip", (route) => json(route, 200, loggedIn));
}

const VIEWPORTS = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "390", width: 390, height: 844 },
] as const;
const THEMES = ["light", "dark"] as const;

for (const theme of THEMES) {
  for (const viewport of VIEWPORTS) {
    test(`Einladung: Passwort, Faktor, Authenticator, Fertig (${theme}, ${viewport.name})`, async ({ browser }) => {
      const context = await browser.newContext({ colorScheme: theme, viewport, storageState: { cookies: [], origins: [] } });
      const page = await context.newPage();
      const shot = (name: string) => page.screenshot({ path: `test-results/invite-${name}-${theme}-${viewport.name}.png`, fullPage: true });
      await mockApi(page, { required: true });

      await page.goto("/auth/set-password#token=e2e-token&kind=invite");
      await expect(page.getByRole("heading", { name: "Konto einrichten" })).toBeVisible();
      await expect(page).toHaveURL(/\/auth\/set-password$/); // Token sofort aus der Adresszeile
      await page.getByLabel("Neues Passwort").fill("BenBeispiel-2026!");
      await expect(page.getByText("Schwach", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Passwort festlegen" })).toBeDisabled();
      await page.getByLabel("Neues Passwort").fill(PASSWORD);
      await page.getByLabel("Passwort wiederholen").fill(PASSWORD);
      await expect(page.getByText("Sehr stark", { exact: true })).toBeVisible();
      await shot("password");

      await page.getByRole("button", { name: "Passwort festlegen" }).click();
      await expect(page.getByRole("heading", { name: "Zweiten Faktor einrichten" })).toBeVisible();
      await expect(page.getByText("Pflicht in Musterverein Seeland.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Später einrichten" })).toHaveCount(0);
      await shot("factor-required");

      await page.getByRole("radio", { name: /Authenticator-App/ }).click();
      await page.getByRole("button", { name: "Weiter" }).click();
      await expect(page.getByRole("heading", { name: "Authenticator-App einrichten" })).toBeVisible();
      if (viewport.name === "390") {
        await expect(page.getByRole("link", { name: "In Authenticator-App öffnen" })).toBeVisible();
      } else {
        await expect(page.getByRole("img", { name: /QR/ })).toBeVisible();
      }
      await page.getByRole("button", { name: "Schlüssel manuell eingeben" }).click();
      await expect(page.getByText("JBSW Y3DP EHPK 3PXP").first()).toBeVisible();
      await page.getByLabel("Code-Ziffer 1").fill("123456");
      await shot("totp");

      await page.getByRole("button", { name: "Aktivieren und anmelden" }).click();
      await expect(page.getByRole("heading", { name: "Alles bereit" })).toBeVisible();
      await expect(page.getByText("ben@beispiel.ch")).toBeVisible();
      await shot("done");
      await context.close();
    });
  }
}

test("Einladung ohne Pflicht: «Später einrichten» mit Rückfrage", async ({ browser }) => {
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const page = await context.newPage();
  await mockApi(page, { required: false });
  await page.goto("/auth/set-password#token=e2e-token&kind=invite");
  await page.getByLabel("Neues Passwort").fill(PASSWORD);
  await page.getByLabel("Passwort wiederholen").fill(PASSWORD);
  await page.getByRole("button", { name: "Passwort festlegen" }).click();
  await page.getByRole("button", { name: "Später einrichten" }).click();
  await expect(page.getByText("Ohne zweiten Faktor weiter?")).toBeVisible();
  await page.screenshot({ path: "test-results/invite-skip-confirm-light-1440.png" });
  await page.getByRole("button", { name: "Überspringen" }).click();
  await expect(page.getByRole("heading", { name: "Alles bereit" })).toBeVisible();
  await expect(page.getByText("Nicht eingerichtet")).toBeVisible();
  await page.screenshot({ path: "test-results/invite-done-skipped-light-1440.png" });
  await context.close();
});

for (const state of ["invalid", "locked"] as const) {
  for (const theme of THEMES) {
    for (const viewport of VIEWPORTS) {
      test(`Einladung ${state} (${theme}, ${viewport.name})`, async ({ browser }) => {
        const context = await browser.newContext({ colorScheme: theme, viewport, storageState: { cookies: [], origins: [] } });
        const page = await context.newPage();
        await mockApi(page, { preview: state });
        await page.goto("/auth/set-password#token=e2e-token&kind=invite");
        await expect(page.getByRole("heading", { name: state === "invalid" ? "Einladung ungültig" : "Kurz gesperrt" })).toBeVisible();
        await expect(page.getByRole("link", { name: "Zur Anmeldung" })).toBeVisible();
        await page.screenshot({ path: `test-results/invite-${state}-${theme}-${viewport.name}.png`, fullPage: true });
        await context.close();
      });
    }
  }
}
