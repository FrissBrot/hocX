import { AdminNotificationSettings } from "@/components/admin/admin-notification-settings";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { NotificationSettings } from "@/types/api";

const EMPTY_SETTINGS: NotificationSettings = {
  ntfy_enabled: false,
  ntfy_server_url: null,
  ntfy_topic: null,
  ntfy_token_set: false,
  admin_url: null,
  reminder_hours: 6,
  status_token: null,
  status_url: null,
  last_sent_at: null,
  last_send_error: null,
  last_send_error_at: null,
};

export default async function AdminNotificationsPage() {
  const session = await requireAdminSession();
  const settings = await backendFetchWithSession<NotificationSettings>("/api/admin/notifications");

  return (
    <AdminShell session={session}>
      <section className="panel">
        <AdminNotificationSettings initialSettings={settings ?? EMPTY_SETTINGS} />
      </section>
    </AdminShell>
  );
}
