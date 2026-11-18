import { notFound, redirect } from "next/navigation";

import { PersonPage } from "@/components/participants/person-page";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { can, featureAccess } from "@/lib/permissions";
import type { FineTariffGroup, ParticipantInvite, ParticipantSummary, RoleRead, TemplateSummary, UserMfaOverview } from "@/types/api";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Personenseite (Konzept «Personen an einem Ort»): Stammdaten, Mitgliedschaft, Tarif, Login und
 * Rollen einer Person. Die Rechte prüft das Backend je Aktion; hier nur die Benutzerführung. */
export default async function PersonDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const session = await requireSession();
  if (!can(session, "participants.manage")) {
    redirect("/");
  }
  if (!UUID_PATTERN.test(id)) {
    notFound();
  }
  const access = can(session, "access.manage");
  const financeRead = can(session, "finances.read") && featureAccess(session, "finance") !== "none";
  const financeManage = can(session, "finances.manage") && featureAccess(session, "finance") === "full";
  const encoded = encodeURIComponent(id);

  const [person, templates, assigned, roles, tariffs, invites] = await Promise.all([
    backendFetchWithSession<ParticipantSummary>(`/api/participants/${encoded}`),
    backendFetchWithSession<TemplateSummary[]>("/api/templates"),
    backendFetchWithSession<TemplateSummary[]>(`/api/participants/${encoded}/templates`),
    access ? backendFetchWithSession<RoleRead[]>("/api/roles") : Promise.resolve(null),
    financeRead ? backendFetchWithSession<FineTariffGroup[]>("/api/todo-fines/tariffs") : Promise.resolve(null),
    access ? backendFetchWithSession<ParticipantInvite[]>("/api/participants/invites") : Promise.resolve(null),
  ]);
  if (!person) {
    notFound();
  }
  // MFA-Status nur für Konten mit Login (Höherberechtigte liefern 403 -> kein Status)
  const mfa = access && person.login_enabled
    ? await backendFetchWithSession<UserMfaOverview>(`/api/users/${encoded}/mfa`)
    : null;

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <PersonPage
          initialPerson={person}
          templates={templates ?? []}
          initialTemplateIds={(assigned ?? []).map((template) => template.id)}
          roles={roles ?? []}
          tariffs={tariffs ?? []}
          initialInvite={(invites ?? []).find((invite) => invite.participant_id === person.id) ?? null}
          initialMfa={mfa}
          permissions={{ access, financeRead, financeManage, dataExport: can(session, "data.export") }}
          actorPermissions={session.permissions ?? []}
          enabledFeatures={session.current_tenant?.enabled_features ?? []}
          ownUserId={session.user?.id ?? null}
          tenantRequiresMfa={Boolean(session.current_tenant?.require_mfa)}
        />
      </section>
    </AppShell>
  );
}
