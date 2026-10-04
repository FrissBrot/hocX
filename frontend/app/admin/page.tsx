import { getTranslations } from "next-intl/server";

import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminTenantPage, AdminUserPage } from "@/types/api";

export default async function AdminDashboardPage() {
  const session = await requireAdminSession();
  const t = await getTranslations("admin.dashboard");
  // No limit param -> full (unpaginated) lists, needed here to compute accurate totals.
  const [tenants, users] = await Promise.all([
    backendFetchWithSession<AdminTenantPage>("/api/admin/tenants"),
    backendFetchWithSession<AdminUserPage>("/api/admin/users"),
  ]);

  const tenantCount = tenants?.total ?? 0;
  const userCount = users?.total ?? 0;
  const activeLoginCount = (users?.items ?? []).filter((user) => user.login_enabled).length;

  return (
    <AdminShell session={session}>
      <section className="panel">
        <div className="eyebrow">{t("eyebrow")}</div>
        <h1>{t("title")}</h1>
        <div className="three-col">
          <div className="card">
            <div className="eyebrow">{t("tenants")}</div>
            <strong style={{ fontSize: "var(--text-3xl)" }}>{tenantCount}</strong>
          </div>
          <div className="card">
            <div className="eyebrow">{t("totalUsers")}</div>
            <strong style={{ fontSize: "var(--text-3xl)" }}>{userCount}</strong>
          </div>
          <div className="card">
            <div className="eyebrow">{t("activeLogins")}</div>
            <strong style={{ fontSize: "var(--text-3xl)" }}>{activeLoginCount}</strong>
          </div>
        </div>
      </section>
    </AdminShell>
  );
}
