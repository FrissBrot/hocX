import { test as setup, expect, request } from "@playwright/test";
import fs from "node:fs/promises";
import { authFiles } from "./auth";
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

// Platform-admin equivalent of authenticate() above - same setup_required/verification_required
// dance, but against /api/admin/auth/* (AdminAuthService/AdminMfaService) rather than
// /api/auth/* (AuthService/MfaService). Kept as its own function rather than a parameterized
// version of authenticate(): the two response shapes (AdminSessionRead vs. the tenant login's
// session/user shape) already differ enough that sharing one function would need as much
// branching as just having two.
async function authenticateAdmin(email: string, file: string) {
  const context = await request.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL });
  const response = await context.post("/api/admin/auth/login", { data: { email, password: process.env.E2E_USER_PASSWORD ?? "ChangeMe123!" } });
  expect(response.ok(), await response.text()).toBeTruthy();
  const body = await response.json();

  if (body.mfa?.status === "setup_required") {
    const start = await context.post("/api/admin/auth/mfa/totp/setup/start", { data: { ticket: body.mfa.ticket } });
    expect(start.ok(), await start.text()).toBeTruthy();
    const { flow_token, secret } = await start.json();
    const complete = await context.post("/api/admin/auth/mfa/totp/setup/complete", {
      data: { flow_token, code: currentTotpCode(secret, Date.now()) },
    });
    expect(complete.ok(), await complete.text()).toBeTruthy();
  } else if (body.mfa) {
    // Unlike the tenant flow above, no spec re-authenticates this same platform-admin
    // account a second time within one run, so there's no remembered secret to answer a
    // later "verification_required" with - see admin-mfa-lockout.spec.ts, which relies on
    // this storageState staying valid for the whole run instead of logging in again.
    throw new Error(`Unexpected admin MFA state for ${email}: ${body.mfa.status} (no remembered TOTP secret to answer it)`);
  }

  await context.storageState({ path: file });
  return context;
}

setup("creates reproducible role and tenant sessions", async () => {
  // Default 45s (playwright.config.ts) can be too tight once the platform-admin login
  // below has to wait out a TOTP anti-replay window (up to 30s, see totp.ts).
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
      role_code: "reader",
    },
  });
  await platformAdmin.dispose();

  const tenantContext = await authenticate(tenantTwoEmail, authFiles.tenantTwo);
  const session = await (await tenantContext.get("/api/auth/session")).json();
  expect(session.current_tenant.id).toBe(regional.id);
  expect(session.current_role).toBe("reader");
  await tenantContext.dispose();
});
