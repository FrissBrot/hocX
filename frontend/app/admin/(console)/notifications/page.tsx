import { redirect } from "next/navigation";

// Alte URL: Konfiguration liegt unter Einstellungen, das Versandprotokoll unter Betrieb › Zustellung.
export default function AdminNotificationsRedirect() {
  redirect("/admin/settings/notifications");
}
