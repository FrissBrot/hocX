import { test, expect, request as playwrightRequest } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { authFiles } from "./auth";
import { uniquePng } from "./unique-fixture";

// Storage-quota enforcement (audit fix, 2026-09-17): Tenant.storage_quota_bytes has been
// computed and *displayed* everywhere (the Speicher page, "Kontingent überschritten") for a
// long time, but no upload path actually enforced it. This test drives the real route the
// "Fotos" gallery upload window itself calls, end to end: the platform admin moves the tenant
// onto a plan whose storage is just above its current usage, then a tenant writer's upload is
// rejected once it would exceed it. Since 0136 the quota comes only from plan + storage
// packages (no manual override endpoint any more), hence the temporary plan.
test("rejects a gallery upload once the tenant's plan storage quota is exceeded", async () => {
  // The accepted upload's ingest is polled up to 60s - the default 45s test timeout
  // (playwright.config.ts) could abort before it finishes.
  test.setTimeout(120_000);
  const writerApi = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.writer });
  const adminApi = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.platformAdmin });
  const planCode = `e2e_quota_${Date.now()}`;
  let tenantId: string | undefined;
  let originalSubscription: Record<string, unknown> | undefined;
  try {
    const session = await (await writerApi.get("/api/auth/session")).json();
    tenantId = session.current_tenant.id as string;
    // The fixture is ~1.5 MB (via a padded, spec-valid ancillary PNG chunk - see the generation
    // note in fixtures/photos/), the temporary plan allows only 1 MB on top of what the tenant
    // already stores - so this one file exceeds the quota regardless of pre-existing usage.
    // Own bytes per run (a repeated run would otherwise hit the exact-duplicate check first).
    const imageBuffer = uniquePng(await fs.readFile(path.join("e2e/fixtures/photos/sample-oversized.png")));

    const tenantResponse = await adminApi.get(`/api/admin/tenants/${tenantId}`);
    expect(tenantResponse.ok(), await tenantResponse.text()).toBeTruthy();
    const tenant = await tenantResponse.json();
    originalSubscription = {
      plan_code: tenant.plan_code,
      billing_cycle: tenant.billing_cycle,
      user_limit_override: tenant.user_limit_override,
      discount_percent: tenant.discount_percent,
      billing_note: tenant.billing_note,
      billing_start_date: tenant.billing_start_date,
    };
    const createPlan = await adminApi.put(`/api/admin/plans/${planCode}`, {
      data: { name: "E2E-Kontingent", included_storage_bytes: tenant.storage_used_bytes + 1024 * 1024, is_bookable: false },
    });
    expect(createPlan.ok(), await createPlan.text()).toBeTruthy();
    const setQuota = await adminApi.patch(`/api/admin/tenants/${tenantId}/subscription`, {
      data: { ...originalSubscription, plan_code: planCode },
    });
    expect(setQuota.ok(), await setQuota.text()).toBeTruthy();

    // The gallery-uploads endpoint reserves the staged bytes against the quota before it
    // queues the gallery_upload_job (files.py's upload_gallery_images calls
    // _enforce_tenant_storage_quota under the tenant upload lock), so an upload that would
    // exceed the quota is rejected synchronously with 400 - no job is ever created for it.
    const postOversized = () =>
      writerApi.post("/api/files/gallery-uploads", {
        multipart: { files: { name: "sample-oversized.png", mimeType: "image/png", buffer: imageBuffer } },
      });

    const rejected = await postOversized();
    expect(rejected.status()).toBe(400);
    expect((await rejected.json()).detail).toContain("Speicherkontingent des Mandanten erreicht");

    // Lifting the quota again must let the identical upload through - proves this is real,
    // reversible enforcement rather than a fixture/checksum-dependent fluke.
    const liftQuota = await adminApi.patch(`/api/admin/tenants/${tenantId}/subscription`, { data: originalSubscription });
    expect(liftQuota.ok(), await liftQuota.text()).toBeTruthy();

    // Once admitted, the background ingest loop processes the queued job.
    const accepted = await postOversized();
    expect(accepted.ok(), await accepted.text()).toBeTruthy();
    const job = await accepted.json();
    await expect
      .poll(async () => (await (await writerApi.get(`/api/files/gallery-upload-jobs/${job.id}`)).json()).status, { timeout: 60_000 })
      .toBe("done");
    const acceptedBody = await (await writerApi.get(`/api/files/gallery-upload-jobs/${job.id}`)).json();
    expect(acceptedBody.imported_items).toHaveLength(1);
  } finally {
    // Always restore the original plan - a leftover tight quota would break every other e2e
    // spec (and the shared demo tenant itself) that uploads anything here afterward.
    if (tenantId && originalSubscription) {
      await adminApi.patch(`/api/admin/tenants/${tenantId}/subscription`, { data: originalSubscription }).catch(() => {});
    }
    await adminApi.delete(`/api/admin/plans/${planCode}`).catch(() => {});
    await writerApi.dispose();
    await adminApi.dispose();
  }
});
