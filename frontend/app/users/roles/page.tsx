import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { RoleManagement } from "@/components/users/role-management";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { userAreaTabs } from "@/components/ui/section-tabs";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { can } from "@/lib/permissions";
import { RoleRead } from "@/types/api";

export default async function RolesPage() {
  const session = await requireSession();
  if (!can(session, "access.manage")) {
    redirect("/");
  }
  const t = await getTranslations("nav");
  const roles = await backendFetchWithSession<RoleRead[]>("/api/roles");

  return (
    <AppShell initialSession={session}>
      <RouteTabs tabs={userAreaTabs(t)} activeHref="/users/roles" />
      <section className="panel">
        <RoleManagement
          initialRoles={roles ?? []}
          actorPermissions={session.permissions ?? []}
          enabledFeatures={session.current_tenant?.enabled_features ?? []}
        />
      </section>
    </AppShell>
  );
}
