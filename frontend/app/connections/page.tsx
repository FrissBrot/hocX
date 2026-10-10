import { ConnectionsView } from "@/components/connections/connections-view";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { CalendarFeed } from "@/types/api";

// "Verknuepfungen" im Benutzermenue: eigene Kalender-Abos, fuer jede Rolle erreichbar (welche
// Kalenderarten angeboten werden, entscheidet ConnectionsView anhand der Rolle).
export default async function ConnectionsPage() {
  const session = await requireSession();
  const feeds = await backendFetchWithSession<CalendarFeed[]>("/api/calendar-feeds");
  const role = session.current_role ?? null;
  const tenantName = session.current_tenant?.name ?? "hocX"; // i18n-ok: Produktname als Rueckfall, kein UI-Text

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<ConnectionsView initialFeeds={feeds ?? []} role={role} tenantName={tenantName} mobile />}
        desktop={
          <section className="panel">
            <ConnectionsView initialFeeds={feeds ?? []} role={role} tenantName={tenantName} />
          </section>
        }
      />
    </AppShell>
  );
}
