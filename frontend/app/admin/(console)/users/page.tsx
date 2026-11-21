import { Suspense } from "react";

import { AdminUserManagement } from "@/components/admin/admin-user-management";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminUserPage } from "@/types/api";

// Mandantenfilter steht in der URL (useServerTable); Mandanten werden per Remote-Picker gesucht
// statt als ganze Liste geladen (1.5.1).
export default async function AdminUsersPage() {
  const page = await backendFetchWithSession<AdminUserPage>("/api/admin/users?limit=50&offset=0");
  return (
    <section className="panel">
      <Suspense fallback={null}>
        <AdminUserManagement initialPage={page ?? { items: [], total: 0 }} />
      </Suspense>
    </section>
  );
}
