import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";

// Bestehende Links öffnen die persönlichen Einstellungen im Profil-Dialog.
export default async function AdminSecurityPage() {
  const session = await requireAdminSession();
  return <AdminShell session={session}>{null}</AdminShell>;
}
