import { MobileUsers } from "@/components/mobile/areas/mobile-admin";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";

import { UserManagement } from "@/components/users/user-management";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { UserSummary } from "@/types/api";

export default async function UsersPage() {
  const session = await requireSession();
  const canAdmin = session.current_role === "admin";

  if (!canAdmin) {
    redirect("/");
  }

  const users = await backendFetchWithSession<UserSummary[]>("/api/users");

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileUsers initialUsers={users ?? []} />}
        desktop={
          <>
          <section className="panel">
            <UserManagement initialUsers={users ?? []} />
          </section>
          </>
        }
      />
    </AppShell>
  );
}
