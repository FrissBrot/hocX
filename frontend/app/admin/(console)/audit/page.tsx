import { redirect } from "next/navigation";

// Alte URL (Lesezeichen): das Audit-Log liegt seit dem Admin-Redesign unter Sicherheit.
export default function AdminAuditRedirect() {
  redirect("/admin/security/audit");
}
