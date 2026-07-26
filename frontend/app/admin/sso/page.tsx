import { AdminSsoSettings } from "@/components/admin/admin-sso-settings";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { PlatformOidcConfigRead } from "@/types/api";

export default async function AdminSsoPage() {
  const session = await requireAdminSession();
  const config = await backendFetchWithSession<PlatformOidcConfigRead>("/api/admin/oidc-config");

  return (
    <AdminShell session={session}>
      <section className="panel">
        <AdminSsoSettings initialConfig={config} />
      </section>
    </AdminShell>
  );
}
