import { test as setup, expect, request } from "@playwright/test";
import fs from "node:fs/promises";
import { authFiles } from "./auth";
import { currentTotpCode, totpCounter, waitForNextTotpWindow } from "./totp";

// Any user with an admin role in any tenant must have MFA before being considered
// authenticated (mfa_service.py's user_requires_mfa). The seeded demo accounts start
// with zero factors, so an admin's first login comes back "setup_required"; a later
// login for the *same* already-enrolled account (this file logs admin@hocx.local in
// twice, for authFiles.admin and again for authFiles.tenantTwo) instead comes back
// "verification_required" - remember each email's TOTP secret (and which 30s counter
// it was last used for, so a later verify can wait out anti-replay) across calls.
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

setup("creates reproducible role and tenant sessions", async () => {
  // Default 45s (playwright.config.ts) can be too tight once the second admin.hocx.local
  // login below has to wait out a TOTP anti-replay window (up to 30s, see totp.ts).
  setup.setTimeout(90_000);
  await fs.mkdir("e2e/.auth", { recursive: true });
  await (await authenticate(process.env.E2E_USER_EMAIL ?? "admin@hocx.local", authFiles.admin)).dispose();
  await (await authenticate("writer@hocx.local", authFiles.writer)).dispose();
  await (await authenticate("reader@hocx.local", authFiles.reader)).dispose();

  const tenantContext = await authenticate(process.env.E2E_USER_EMAIL ?? "admin@hocx.local", authFiles.tenantTwo);
  const session = await (await tenantContext.get("/api/auth/session")).json();
  expect(session.available_tenants.length).toBeGreaterThan(1);
  const secondTenant = session.available_tenants.find((entry: { tenant_id: string }) => entry.tenant_id !== session.current_tenant.id);
  expect(secondTenant).toBeTruthy();
  const selected = await tenantContext.post(`/api/auth/select-tenant/${secondTenant.tenant_id}`);
  expect(selected.ok(), await selected.text()).toBeTruthy();
  await tenantContext.storageState({ path: authFiles.tenantTwo });
  await tenantContext.dispose();
});
