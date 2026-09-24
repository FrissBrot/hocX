import { test, expect, request as playwrightRequest } from "@playwright/test";
import { authFiles } from "./auth";

// Speicher-Zusatzpakete (0087_storage_packages): ein Admin legt ein Paket im Preiskatalog an,
// weist es einem Mandanten zu und der Mandant sieht die korrekte Aufschlüsselung
// (Plan-Anteil + Zusatzpaket-Anteil) in seinem eigenen Abo. API-getrieben statt UI-Klicks, wie
// feature-gating.spec.ts - der Katalog-Code ist zeitgestempelt, damit parallele Testläufe sich
// nicht dieselbe Zeile teilen.
test("admin creates a storage package, assigns it to a tenant, and the tenant sees the breakdown", async ({}) => {
  // GET /api/tenants/{id}/subscription requires the tenant-admin role (_manageable_tenant_ids
  // in tenant_service.py only admits role=="admin") - a writer gets 403 here, unlike the other
  // tenant-scoped routes in feature-gating.spec.ts.
  const tenantAdminApi = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.admin });
  const adminApi = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.platformAdmin });
  const packageCode = `e2e_pkg_${Date.now()}`;
  let tenantId: string | undefined;
  try {
    const session = await (await tenantAdminApi.get("/api/auth/session")).json();
    tenantId = session.current_tenant.id as string;

    const createPackage = await adminApi.put(`/api/admin/storage-packages/${packageCode}`, {
      data: { name: "E2E-Testpaket", bytes: 1_000_000_000, price_monthly_rp: 500, price_yearly_rp: 5000, sort_order: 0 },
    });
    expect(createPackage.ok(), await createPackage.text()).toBeTruthy();

    const beforeResponse = await tenantAdminApi.get(`/api/tenants/${tenantId}/subscription`);
    expect(beforeResponse.ok(), await beforeResponse.text()).toBeTruthy();
    const beforeSubscription = await beforeResponse.json();
    const planStorageBytes: number | null = beforeSubscription.included_storage_bytes;

    const assign = await adminApi.put(`/api/admin/tenants/${tenantId}/storage-packages`, {
      data: { items: [{ package_code: packageCode, quantity: 2 }] },
    });
    expect(assign.ok(), await assign.text()).toBeTruthy();
    const assignedTenant = await assign.json();
    expect(assignedTenant.package_storage_bytes).toBe(2_000_000_000);
    expect(assignedTenant.effective_storage_quota_bytes).toBe((planStorageBytes ?? 0) + 2_000_000_000);
    expect(assignedTenant.assigned_storage_packages).toEqual([
      expect.objectContaining({ package_code: packageCode, quantity: 2, bytes: 1_000_000_000, total_bytes: 2_000_000_000 }),
    ]);

    const afterResponse = await tenantAdminApi.get(`/api/tenants/${tenantId}/subscription`);
    expect(afterResponse.ok(), await afterResponse.text()).toBeTruthy();
    const afterSubscription = await afterResponse.json();
    expect(afterSubscription.package_storage_bytes).toBe(2_000_000_000);
    expect(afterSubscription.storage_quota_bytes).toBe((planStorageBytes ?? 0) + 2_000_000_000);
    expect(afterSubscription.storage_quota_manual_override).toBe(false);
  } finally {
    if (tenantId) {
      await adminApi.put(`/api/admin/tenants/${tenantId}/storage-packages`, { data: { items: [] } }).catch(() => {});
    }
    await tenantAdminApi.dispose();
    await adminApi.dispose();
  }
});
