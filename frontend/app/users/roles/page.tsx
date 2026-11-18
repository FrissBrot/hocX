import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { RoleManagement } from "@/components/users/role-management";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { userAreaTabs } from "@/components/ui/section-tabs";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { FeatureNotice } from "@/components/ui/feature-notice";
import { can, featureAccess } from "@/lib/permissions";
import { RoleRead } from "@/types/api";

export default async function RolesPage({ searchParams }: { searchParams: Promise<{ role?: string }> }) {
  // Deep-Link /users/roles?role=<public_id> (z. B. aus der Ctrl+K-Suche): Rolle direkt öffnen
  const { role } = await searchParams;
  const session = await requireSession();
  if (!can(session, "access.manage")) {
    redirect("/");
  }
  const t = await getTranslations("nav");
  const roles = await backendFetchWithSession<RoleRead[]>("/api/roles");
  const customRoles = featureAccess(session, "custom_roles");

  return (
    <AppShell initialSession={session}>
      <RouteTabs tabs={userAreaTabs(t)} activeHref="/users/roles" />
      <FeatureNotice feature="custom_roles" access={customRoles} />
      <section className="panel">
        <RoleManagement
          initialRoles={roles ?? []}
          actorPermissions={session.permissions ?? []}
          actorAssignedOnly={session.assigned_only ?? []}
          enabledFeatures={session.current_tenant?.enabled_features ?? []}
          canCustomize={customRoles === "full"}
          initialRoleId={role ?? null}
        />
      </section>
    </AppShell>
  );
}
