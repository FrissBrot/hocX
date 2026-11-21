import { AdminEmailSettings } from "@/components/admin/admin-email-settings";
import { AdminNotificationSettings } from "@/components/admin/admin-notification-settings";
import { backendFetchWithSession } from "@/lib/api/server";
import { EmailSettings, NotificationSettings } from "@/types/api";

const EMPTY_SETTINGS: NotificationSettings = {
  ntfy_enabled: false,
  ntfy_server_url: null,
  ntfy_topic: null,
  ntfy_token_set: false,
  admin_url: null,
  reminder_hours: 6,
  status_token: null,
  status_token_set: false,
  status_token_hint: null,
  status_url: null,
  last_sent_at: null,
  last_send_error: null,
  last_send_error_at: null,
};

export default async function AdminNotificationsPage() {
  const [settings, emailSettings] = await Promise.all([
    backendFetchWithSession<NotificationSettings>("/api/admin/notifications"),
    backendFetchWithSession<EmailSettings>("/api/admin/notifications/email"),
  ]);

  return (
    <>
      <section className="panel">
        <AdminNotificationSettings initialSettings={settings ?? EMPTY_SETTINGS} />
      </section>
      <section className="panel">
        {emailSettings ? <AdminEmailSettings initialSettings={emailSettings} /> : null}
      </section>
    </>
  );
}
