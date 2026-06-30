import { redirect } from "next/navigation";

import { UserManagement } from "@/components/users/user-management";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { TenantSummary, UserSummary } from "@/types/api";

export default async function UsersPage() {
  const session = await requireSession();
  const canAdmin = session.user?.is_superadmin || session.current_role === "admin";

  if (!canAdmin) {
    redirect("/");
  }

  const [users, tenants] = await Promise.all([
    backendFetchWithSession<UserSummary[]>("/api/users"),
    backendFetchWithSession<TenantSummary[]>("/api/tenants")
  ]);

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <UserManagement initialUsers={users ?? []} manageableTenants={tenants ?? []} session={session} />
      </section>
    </AppShell>
  );
}
