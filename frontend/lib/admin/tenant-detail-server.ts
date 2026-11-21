import { cache } from "react";
import { notFound } from "next/navigation";

import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminTenantSummary } from "@/types/api";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Mandant der Detailseite /admin/tenants/[id] - einmal pro Render (Layout und Tab teilen den Abruf). */
export const loadAdminTenant = cache(async function loadAdminTenant(id: string): Promise<AdminTenantSummary> {
  if (!UUID_PATTERN.test(id)) notFound();
  const tenant = await backendFetchWithSession<AdminTenantSummary>(`/api/admin/tenants/${id}`);
  if (tenant === null) notFound();
  return tenant;
});

/** Sensible Lesezugriffe (Benutzer, Audit, Fehler) sind im Backend nur für owner (require_admin_owner). */
export async function adminIsOwner(): Promise<boolean> {
  const session = await requireAdminSession();
  return session.admin?.role === "owner"; // rbac-ok: Plattform-Admin-Rolle (owner/support), kein Mandanten-Rollen-Code
}
