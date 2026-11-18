import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { AccessSecurity } from "@/components/users/access-security";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { userAreaTabs } from "@/components/ui/section-tabs";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { can } from "@/lib/permissions";
import { TenantMfaPolicy } from "@/types/api";

export default async function AccessSecurityPage() {
  const session = await requireSession();
  if (!can(session, "access.manage")) {
    redirect("/");
  }
  const t = await getTranslations("nav");
  const policy = await backendFetchWithSession<TenantMfaPolicy>("/api/users/mfa-policy");

  return (
    <AppShell initialSession={session}>
      <RouteTabs tabs={userAreaTabs(t)} activeHref="/users/security" />
      <section className="panel">
        <AccessSecurity initialPolicy={policy} />
      </section>
    </AppShell>
  );
}
