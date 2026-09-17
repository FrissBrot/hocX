import { test, expect } from "@playwright/test";
import { authFiles } from "./auth";
import { addVirtualAuthenticator } from "./webauthn";

// Platform-admin MFA self-lockout protection (audit fix, 2026-09-17): deleting the last TOTP
// factor used to be allowed as long as *some* factor (e.g. a webauthn passkey) survived, even
// though the admin login flow only ever verifies TOTP (never a passkey) - so that combination
// silently, permanently locked the admin out with no recovery path. admin-mfa-settings.tsx's
// client-side guard (isLastFactor = factors.length <= 1) doesn't know about this TOTP-specific
// case either - with a passkey present, the "Entfernen" button on the last TOTP factor stays
// enabled, and only the server's 409 actually stops the deletion. This is the one test that
// proves that end to end through the real page, not just admin_mfa_service.py directly (see
// tests/test_admin_mfa_service.py for the service-level coverage this complements).
//
// WebAuthn needs a real domain, not an IP literal: Chromium rejects rp.id "127.0.0.1" with
// "This is an invalid domain" (WebAuthn's RP ID must be a valid domain string, which
// excludes IP literals even though 127.0.0.1 is otherwise a fine "secure context" for
// everything else this suite does). "localhost" is the one non-routable name Chromium
// still accepts for it, so this spec swaps in a "localhost"-addressed context instead of
// the project's usual PLAYWRIGHT_BASE_URL/authFiles.platformAdmin (both 127.0.0.1-scoped) -
// reusing the *same* already-TOTP-enrolled admin session by cloning its session cookie onto
// the "localhost" domain, rather than logging in fresh (which would hit
// "verification_required" for an account auth.setup.ts already enrolled, with no
// remembered TOTP secret here to answer it).
test("blocks deleting the platform admin's last TOTP factor while a passkey survives", async ({ browser }) => {
  const localhostBaseURL = (process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:13000").replace("127.0.0.1", "localhost");
  const seedContext = await browser.newContext({ storageState: authFiles.platformAdmin });
  const sessionCookies = await seedContext.cookies();
  await seedContext.close();

  const context = await browser.newContext({ baseURL: localhostBaseURL });
  await context.addCookies(sessionCookies.map((cookie) => ({ ...cookie, domain: "localhost" })));
  const page = await context.newPage();

  // A previous run of this same spec (or a retry within one run) may have already left a
  // passkey enrolled on this shared platform-admin account - clean those up first so the
  // "2 factors total" assertions below hold regardless of how many times this has run
  // before, rather than accumulating one more passkey per run forever.
  const overview = await (await context.request.get("/api/admin/mfa")).json();
  for (const factor of overview.factors) {
    if (factor.factor_type === "webauthn") {
      await context.request.delete(`/api/admin/mfa/factors/${factor.id}`);
    }
  }

  const removeAuthenticator = await addVirtualAuthenticator(page);
  try {
    await page.goto("/admin/security");
    await expect(page.getByText("Zwei-Faktor-Authentifizierung")).toBeVisible();

    // auth.setup.ts already enrolled this platform admin's one TOTP factor during login -
    // the "Authenticator-App" card should already show it as set up.
    const totpCard = page.locator(".security-method-card", { hasText: "Authenticator-App" });
    await expect(totpCard.getByText("Eingerichtet")).toBeVisible();

    // Enrol a passkey through the real WebAuthn ceremony (routed to the CDP virtual
    // authenticator above) - this is the second factor the audit's regression needs present.
    await page.getByRole("button", { name: "Passkey hinzufügen" }).click();
    await expect(page.locator(".app-toast", { hasText: "Passkey erfolgreich eingerichtet" })).toBeVisible();

    await expect(page.locator(".security-factor-card")).toHaveCount(2);
    const totpFactorRow = page.locator(".security-factor-card", { hasText: "TOTP" });
    await expect(totpFactorRow).toBeVisible();
    // The audit's exact bug: with 2 factors total, the client's isLastFactor check
    // (factors.length <= 1) is false, so nothing disables this button - only the
    // server-side check below is what actually has to stop the deletion.
    await expect(totpFactorRow.getByRole("button", { name: "Entfernen" })).toBeEnabled();

    await totpFactorRow.getByRole("button", { name: "Entfernen" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Entfernen" }).click();

    // Scoped to the error-styled toast specifically - the earlier "Passkey erfolgreich
    // eingerichtet" success toast can still be on screen (toasts don't all dismiss
    // instantly), and a bare role=alert also matches Next.js's own route-announcer div.
    await expect(page.locator(".app-toast-error")).toContainText("müssen mindestens eine Authenticator-App (TOTP) behalten");

    // The factor must genuinely still be there - the request must have been rejected, not
    // just warned about client-side after already succeeding.
    await expect(page.locator(".security-factor-card")).toHaveCount(2);
    await expect(totpFactorRow).toBeVisible();
  } finally {
    await removeAuthenticator();
    await context.close();
  }
});
