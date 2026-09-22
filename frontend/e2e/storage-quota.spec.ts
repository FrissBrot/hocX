import { test, expect, request as playwrightRequest } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { authFiles } from "./auth";
import { uniquePng } from "./unique-fixture";

// Storage-quota enforcement (audit fix, 2026-09-17): Tenant.storage_quota_bytes has been
// computed and *displayed* everywhere (the Speicher page, "Kontingent überschritten") for a
// long time, but no upload path actually enforced it - an admin's configured limit had zero
// effect on whether uploads kept succeeding. This is new, real blocking behavior (previously
// purely cosmetic), and until now was only exercised at the service level against mocked
// storage (tests/test_upload_pipeline_quota.py calls ingest_file() directly) - never through
// a real HTTP request. This test drives the real route the "Fotos" gallery upload window
// itself calls, end to end: platform admin sets the quota, then a tenant writer's upload is
// rejected once it would exceed it.
test("rejects a gallery upload once the platform-admin-configured storage quota is exceeded", async () => {
  // Two full upload+ingest round trips, each polled up to 60s (see uploadOversized below) -
  // the default 45s test timeout (playwright.config.ts) would abort before either finishes.
  test.setTimeout(120_000);
  const writerApi = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.writer });
  const adminApi = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.platformAdmin });
  let tenantId: string | undefined;
  try {
    const session = await (await writerApi.get("/api/auth/session")).json();
    tenantId = session.current_tenant.id as string;
    // AdminTenantStorageQuotaUpdate requires quota_mb >= 1 (no all-uploads-blocked "0"
    // option), so instead of relying on the shared demo tenant already having close to 1 MB
    // stored, this fixture is itself ~1.5 MB (via a padded, spec-valid ancillary PNG chunk -
    // see the generation note in fixtures/photos/) - bigger than the smallest quota the API
    // allows, so the check is exceeded on this one file alone regardless of pre-existing
    // usage.
    // Own bytes per run (a repeated run would otherwise hit the exact-duplicate check first).
    const imageBuffer = uniquePng(await fs.readFile(path.join("e2e/fixtures/photos/sample-oversized.png")));

    const setQuota = await adminApi.patch(`/api/admin/tenants/${tenantId}/storage-quota`, { data: { quota_mb: 1 } });
    expect(setQuota.ok(), await setQuota.text()).toBeTruthy();

    // The gallery-uploads endpoint only stages the file and queues a gallery_upload_job
    // (201) - the quota check itself happens when the background ingest loop processes it
    // (file_service.py's save_gallery_uploads), and one bad file never fails the job as a
    // whole: it ends "done" with the problem in the job detail's `errors` while
    // `imported_items` stays empty for it.
    const uploadOversized = async () => {
      const response = await writerApi.post("/api/files/gallery-uploads", {
        multipart: { files: { name: "sample-oversized.png", mimeType: "image/png", buffer: imageBuffer } },
      });
      expect(response.ok(), await response.text()).toBeTruthy();
      const job = await response.json();
      await expect
        .poll(async () => (await (await writerApi.get(`/api/files/gallery-upload-jobs/${job.id}`)).json()).status, { timeout: 60_000 })
        .toBe("done");
      return (await writerApi.get(`/api/files/gallery-upload-jobs/${job.id}`)).json();
    };

    const rejectedBody = await uploadOversized();
    expect(rejectedBody.imported_items).toHaveLength(0);
    expect(rejectedBody.errors.join(" ")).toContain("Speicherkontingent des Mandanten erreicht");

    // Lifting the quota again must let the identical upload through - proves this is real,
    // reversible enforcement rather than a fixture/checksum-dependent fluke.
    const liftQuota = await adminApi.patch(`/api/admin/tenants/${tenantId}/storage-quota`, { data: { quota_mb: null } });
    expect(liftQuota.ok(), await liftQuota.text()).toBeTruthy();

    const acceptedBody = await uploadOversized();
    expect(acceptedBody.imported_items).toHaveLength(1);
  } finally {
    // Always restore "no quota" - a leftover 0-byte quota would break every other e2e spec
    // (and the shared demo tenant itself) that uploads anything here afterward.
    if (tenantId) {
      await adminApi.patch(`/api/admin/tenants/${tenantId}/storage-quota`, { data: { quota_mb: null } }).catch(() => {});
    }
    await writerApi.dispose();
    await adminApi.dispose();
  }
});
