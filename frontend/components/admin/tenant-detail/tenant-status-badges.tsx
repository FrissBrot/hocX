"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { deriveTenantStatus } from "@/lib/admin/tenant-status";
import { AdminTenantSummary } from "@/types/api";

/** Abgeleitete Status als Badges mit Text (nie nur Farbe). `compact`: in der Liste «aktiv» weglassen. */
export function TenantStatusBadges({ tenant, compact = false }: { tenant: AdminTenantSummary; compact?: boolean }) {
  const t = useTranslations("adminTenantDetail.status");
  const statuses = deriveTenantStatus(tenant).filter((status) => !(compact && status.key === "active"));
  if (statuses.length === 0) return null;
  return (
    <span className="admin-tenant-status-badges">
      {statuses.map((status) => (
        <Badge key={status.key} variant={status.variant} dot>
          {t(status.key)}
        </Badge>
      ))}
    </span>
  );
}
