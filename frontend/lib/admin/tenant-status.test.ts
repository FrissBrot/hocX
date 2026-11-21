import { describe, expect, it } from "vitest";

import { deriveTenantStatus } from "@/lib/admin/tenant-status";
import { DEFAULT_TENANT_VIEW, tenantListQuery, tenantViewFromParams } from "@/lib/admin/tenant-list";

const NOW = new Date(2026, 10, 21);
const base = { read_only_features: [] as string[], contract_ends_on: null as string | null, identity_verified_at: "2026-01-01T00:00:00Z" };

describe("deriveTenantStatus", () => {
  it("ohne Einschränkung ist der Mandant aktiv", () => {
    expect(deriveTenantStatus(base, NOW).map((s) => s.key)).toEqual(["active"]);
  });

  it("leitet Nur-Lesen, Vertragsende (<30 Tage) und fehlende Verifizierung ab", () => {
    const keys = deriveTenantStatus({ read_only_features: ["finance"], contract_ends_on: "2026-12-10", identity_verified_at: null }, NOW).map((s) => s.key);
    expect(keys).toEqual(["readOnly", "contractEnding", "unverified"]);
  });

  it("Vertragsende in 30 Tagen oder später gilt noch nicht als «endet»", () => {
    expect(deriveTenantStatus({ ...base, contract_ends_on: "2026-12-21" }, NOW).map((s) => s.key)).toEqual(["active"]);
    expect(deriveTenantStatus({ ...base, contract_ends_on: "2026-12-20" }, NOW).map((s) => s.key)).toEqual(["contractEnding"]);
  });

  it("unbekannte Verifizierung (Feld fehlt) wird nicht als «nicht verifiziert» gezeigt", () => {
    expect(deriveTenantStatus({ read_only_features: [], contract_ends_on: null }, NOW).map((s) => s.key)).toEqual(["active"]);
  });
});

describe("Mandantenliste: URL-Zustand", () => {
  it("lässt Standardwerte weg und übernimmt Filter", () => {
    expect(tenantListQuery(DEFAULT_TENANT_VIEW, "").toString()).toBe("");
    const query = tenantListQuery({ sort: "storage", dir: "desc", status: "unverified", storageFull: true, q: " Verein " }, "pro");
    expect(Object.fromEntries(query)).toEqual({ q: "Verein", plan: "pro", sort: "storage", dir: "desc", status: "unverified", storage_min_ratio: "0.85" });
  });

  it("verwirft unbekannte Werte aus der URL", () => {
    expect(tenantViewFromParams({ sort: "evil", dir: "sideways", status: "deleted" })).toEqual(DEFAULT_TENANT_VIEW);
    expect(tenantViewFromParams({ sort: "users", dir: "desc", status: "read_only", storage_min_ratio: "0.85" })).toMatchObject({
      sort: "users",
      dir: "desc",
      status: "read_only",
      storageFull: true,
    });
  });
});
