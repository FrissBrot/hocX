import { MobileUsers } from "@/components/mobile/areas/mobile-admin";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { AccessOverview } from "@/components/users/access-overview";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { userAreaTabs } from "@/components/ui/section-tabs";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { ParticipantInvite, RoleRead, UserSummary } from "@/types/api";
import { can } from "@/lib/permissions";

export default async function UsersPage() {
  const session = await requireSession();
  const canAdmin = can(session, "access.manage");

  if (!canAdmin) {
    redirect("/");
  }

  const t = await getTranslations("nav");
  const [users, roles, invites] = await Promise.all([
    backendFetchWithSession<UserSummary[]>("/api/users"),
    backendFetchWithSession<RoleRead[]>("/api/roles"),
    backendFetchWithSession<ParticipantInvite[]>("/api/participants/invites"),
  ]);
  const access = {
    roles: roles ?? [],
    actorPermissions: session.permissions ?? [],
    enabledFeatures: session.current_tenant?.enabled_features ?? [],
  };

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileUsers initialUsers={users ?? []} {...access} />}
        desktop={
          <>
          <RouteTabs tabs={userAreaTabs(t)} activeHref="/users" />
          <section className="panel">
            <AccessOverview
              users={users ?? []}
              invites={invites ?? []}
              roles={roles ?? []}
              tenantRequiresMfa={Boolean(session.current_tenant?.require_mfa)}
            />
          </section>
          </>
        }
      />
    </AppShell>
  );
}
