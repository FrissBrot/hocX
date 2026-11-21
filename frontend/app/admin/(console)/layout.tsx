import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { getServerVersion } from "@/lib/server-version";

// Konsole des Plattform-Admins: Die Shell (Navigation, Suche, Zähler, Toast/Confirm-Provider) wird
// einmal pro Sitzung hier gemountet statt auf jeder Seite neu. /admin/login liegt ausserhalb dieser
// Route-Gruppe und bleibt ohne Shell.
export default async function AdminConsoleLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const session = await requireAdminSession();
  // Umgebungs-Badge in der Kopfleiste (Test/Dev farbig), damit die Produktion unterscheidbar ist
  const { environment } = getServerVersion();
  return <AdminShell session={session} environment={environment}>{children}</AdminShell>;
}
