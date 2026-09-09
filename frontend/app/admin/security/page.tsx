import { AdminMfaSettings } from "@/components/admin/admin-mfa-settings";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { UserMfaOverview } from "@/types/api";

const emptyOverview: UserMfaOverview = {
  required: true,
  has_factors: false,
  can_add_passkey_here: false,
  preferred_factor_type: null,
  preferred_factor_label: null,
  factors: [],
};

export default async function AdminSecurityPage() {
  const session = await requireAdminSession();
  const overview = await backendFetchWithSession<UserMfaOverview>("/api/admin/mfa");

  return (
    <AdminShell session={session}>
      <section className="panel">
        <AdminMfaSettings initialOverview={overview ?? emptyOverview} />
      </section>
    </AdminShell>
  );
}
