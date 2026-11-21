"use client";

import { useTranslations } from "next-intl";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { StatusBanner } from "@/components/ui/status-banner";
import { useAdminResource } from "@/components/admin/security/use-admin-resource";
import type { AuthPolicy } from "@/types/admin-security";

const GROUPS = ["sessions", "limits", "blocks", "risk", "step_up", "alerts", "retention"] as const;

/** Wirksame Anmeldeschutz-Einstellungen, nur Anzeige. Der technische Name ist bewusst sichtbar: er ist
 * der Schlüssel in der Server-Konfiguration (Umgebungsvariable in Grossbuchstaben). */
export function SecurityPolicyView() {
  const t = useTranslations("adminSecurity");
  const policy = useAdminResource<AuthPolicy>("/api/admin/auth-security/policy");
  if (policy.forbidden) return <StatusBanner tone="neutral" message={t("ownerOnly")} />;
  if (policy.failed) return <StatusBanner tone="error" message={t("loadFailed")} />;
  return (
    <div className="section-stack">
      {GROUPS.filter((group) => policy.data?.[group]).map((group) => (
        <section className="card section-stack" key={group}>
          <DataToolbar title={t(`policy.groups.${group}`)} />
          <DataTable columns={[t("policy.setting"), t("policy.value")]}>
            {Object.entries(policy.data?.[group] ?? {}).map(([name, value]) => (
              <tr key={name}>
                <td><code>{name.toUpperCase()}</code></td>
                <td>{typeof value === "boolean" ? (value ? t("policy.yes") : t("policy.no")) : String(value)}</td>
              </tr>
            ))}
          </DataTable>
        </section>
      ))}
    </div>
  );
}
