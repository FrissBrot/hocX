import { test as setup, expect, request } from "@playwright/test";
import fs from "node:fs/promises";
import { authFiles } from "./auth";

async function authenticate(email: string, file: string) {
  const context = await request.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL });
  const response = await context.post("/api/auth/login", { data: { email, password: process.env.E2E_USER_PASSWORD ?? "ChangeMe123!" } });
  expect(response.ok(), await response.text()).toBeTruthy();
  await context.storageState({ path: file });
  return context;
}

setup("creates reproducible role and tenant sessions", async () => {
  await fs.mkdir("e2e/.auth", { recursive: true });
  await (await authenticate(process.env.E2E_USER_EMAIL ?? "admin@hocx.local", authFiles.admin)).dispose();
  await (await authenticate("writer@hocx.local", authFiles.writer)).dispose();
  await (await authenticate("reader@hocx.local", authFiles.reader)).dispose();

  const tenantContext = await authenticate(process.env.E2E_USER_EMAIL ?? "admin@hocx.local", authFiles.tenantTwo);
  const session = await (await tenantContext.get("/api/auth/session")).json();
  expect(session.tenants.length).toBeGreaterThan(1);
  const secondTenant = session.tenants.find((entry: { tenant_id: string }) => entry.tenant_id !== session.current_tenant_id);
  expect(secondTenant).toBeTruthy();
  const selected = await tenantContext.post(`/api/auth/select-tenant/${secondTenant.tenant_id}`);
  expect(selected.ok(), await selected.text()).toBeTruthy();
  await tenantContext.storageState({ path: authFiles.tenantTwo });
  await tenantContext.dispose();
});
