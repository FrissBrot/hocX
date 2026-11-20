import { test as setup, expect, request } from "@playwright/test";
import fs from "node:fs/promises";
import { authFiles, platformAdminPasskeyFile } from "./auth";
import { SoftPasskey } from "./soft-passkey";
import { currentTotpCode, totpCounter, waitForNextTotpWindow } from "./totp";

// Any user with an admin role in any tenant must have MFA before being considered
// authenticated (mfa_service.py's user_requires_mfa). The seeded demo accounts start
// with zero factors, so an admin's first login comes back "setup_required"; a later
// login for the *same* already-enrolled account (this file logs admin@hocx.local in
// once for authFiles.admin) instead comes back
// "verification_required" - remember each email's TOTP secret (and which 30s counter
// it was last used for, so a later verify can wait out anti-replay) across calls.
const tenantTwoEmail = "reader-regional@hocx.local";
const totpFactors = new Map<string, { secret: string; lastCounter: number }>();

async function authenticate(email: string, file: string) {
  const context = await request.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL });
  const response = await context.post("/api/auth/login", { data: { email, password: process.env.E2E_USER_PASSWORD ?? "ChangeMe123!" } });
  expect(response.ok(), await response.text()).toBeTruthy();
  const body = await response.json();

  if (body.mfa?.status === "setup_required") {
    // Complete TOTP enrolment through the same ticket-based flow the real login page uses.
    const start = await context.post("/api/auth/mfa/totp/setup/start", { data: { ticket: body.mfa.ticket } });
    expect(start.ok(), await start.text()).toBeTruthy();
    const { flow_token, secret } = await start.json();
    const now = Date.now();
    const complete = await context.post("/api/auth/mfa/totp/setup/complete", {
      data: { flow_token, code: currentTotpCode(secret, now) },
    });
    expect(complete.ok(), await complete.text()).toBeTruthy();
    totpFactors.set(email, { secret, lastCounter: totpCounter(now) });
  } else if (body.mfa?.status === "verification_required") {
    const factor = totpFactors.get(email);
    if (!factor) throw new Error(`No remembered TOTP secret for ${email} to answer "verification_required"`);
    await waitForNextTotpWindow(factor.lastCounter);
    const now = Date.now();
    const verify = await context.post("/api/auth/mfa/totp/verify", {
      data: { ticket: body.mfa.ticket, code: currentTotpCode(factor.secret, now) },
    });
    expect(verify.ok(), await verify.text()).toBeTruthy();
    factor.lastCounter = totpCounter(now);
  } else if (body.mfa) {
    throw new Error(`Unexpected MFA state for ${email}: ${body.mfa.status}`);
  }

  await context.storageState({ path: file });
  return context;
}

// Plattform-Admin: Passwort + Passkey (kein TOTP mehr, backend admin_mfa_service.py). Ohne Passkey
// kommt "setup_required" (Trust on first use), danach "verification_required". Der Software-Passkey
// (soft-passkey.ts) wird neben den Sessions gespeichert, damit ein späterer Lauf gegen denselben
// E2E-Stack sich wieder anmelden kann.
async function authenticateAdmin(email: string, file: string) {
  const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:13000";
  const origin = new URL(baseURL).origin;
  // Origin wie im Browser: daraus leitet das Backend ohne Admin-Domain RP-ID und Origin ab.
  const context = await request.newContext({ baseURL, extraHTTPHeaders: { Origin: origin } });
  const response = await context.post("/api/admin/auth/login", { data: { email, password: process.env.E2E_USER_PASSWORD ?? "ChangeMe123!" } });
  expect(response.ok(), await response.text()).toBeTruthy();
  const body = await response.json();

  if (body.mfa?.status === "setup_required") {
    const passkey = SoftPasskey.create();
    const start = await context.post("/api/admin/auth/mfa/passkey/setup/start", { data: { ticket: body.mfa.ticket } });
    expect(start.ok(), await start.text()).toBeTruthy();
    const { flow_token, public_key } = await start.json();
    const complete = await context.post("/api/admin/auth/mfa/passkey/setup/complete", {
      data: { flow_token, label: "E2E-Software-Passkey", credential: passkey.registration(public_key, origin) },
    });
    expect(complete.ok(), await complete.text()).toBeTruthy();
    await passkey.save(platformAdminPasskeyFile);
  } else if (body.mfa?.status === "verification_required") {
    const passkey = await SoftPasskey.load(platformAdminPasskeyFile);
    if (!passkey) throw new Error(`${email} hat schon einen Passkey, ${platformAdminPasskeyFile} fehlt (E2E-Stack neu aufsetzen)`);
    const start = await context.post("/api/admin/auth/mfa/passkey/start", { data: { ticket: body.mfa.ticket } });
    expect(start.ok(), await start.text()).toBeTruthy();
    const { flow_token, public_key } = await start.json();
    const verify = await context.post("/api/admin/auth/mfa/passkey/verify", {
      data: { flow_token, credential: passkey.assertion(public_key, origin) },
    });
    expect(verify.ok(), await verify.text()).toBeTruthy();
    await passkey.save(platformAdminPasskeyFile);
  } else if (body.mfa) {
    throw new Error(`Unexpected admin MFA state for ${email}: ${body.mfa.status}`);
  }

  await context.storageState({ path: file });
  return context;
}

setup("creates reproducible role and tenant sessions", async () => {
  // Default 45s (playwright.config.ts) can be too tight when the tenant logins below have to wait
  // out a TOTP anti-replay window (up to 30s, see totp.ts).
  setup.setTimeout(90_000);
  await fs.mkdir("e2e/.auth", { recursive: true });
  await (await authenticate(process.env.E2E_USER_EMAIL ?? "admin@hocx.local", authFiles.admin)).dispose();
  await (await authenticate("writer@hocx.local", authFiles.writer)).dispose();
  await (await authenticate("reader@hocx.local", authFiles.reader)).dispose();
  const platformAdmin = await authenticateAdmin("platform-admin@hocx.local", authFiles.platformAdmin);

  // Jedes Konto gehört genau einem Mandanten, ein Konto mit "zweitem Mandanten" gibt es nicht
  // mehr. Für die Mandantengrenz-Specs (authFiles.tenantTwo) legt das Platform-Admin-Panel darum
  // einen Leser im zweiten Demo-Mandanten an (idempotent: existiert er schon, schlägt nur das
  // Anlegen fehl und der Login darunter beweist, dass das Konto brauchbar ist).
  const tenants = await (await platformAdmin.get("/api/admin/tenants")).json();
  const regional = tenants.items.find((entry: { name: string }) => entry.name === "Regional Workspace");
  expect(regional, "Demo-Mandant 'Regional Workspace' fehlt").toBeTruthy();
  await platformAdmin.post("/api/admin/users", {
    data: {
      first_name: "Regional",
      last_name: "Reader",
      display_name: "Regional Reader",
      email: tenantTwoEmail,
      password: process.env.E2E_USER_PASSWORD ?? "ChangeMe123!",
      tenant_id: regional.id,
      system_role: "reader",
      login_enabled: true,
    },
  });
  await platformAdmin.dispose();

  const tenantContext = await authenticate(tenantTwoEmail, authFiles.tenantTwo);
  const session = await (await tenantContext.get("/api/auth/session")).json();
  expect(session.current_tenant.id).toBe(regional.id);
  expect(session.roles.map((role: { system_key: string | null }) => role.system_key)).toEqual(["reader"]);
  expect(session.permissions).toContain("meetings.read");
  expect(session.permissions).not.toContain("meetings.edit");
  await tenantContext.dispose();
});
