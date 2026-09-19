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
      <section className="panel">
        <UserManagement initialUsers={users ?? []} />
      </section>
    </AppShell>
  );
}
