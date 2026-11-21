"use client";

import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { StatusBanner } from "@/components/ui/status-banner";
import { useAdminResource } from "@/components/admin/security/use-admin-resource";
import { Modal } from "@/components/ui/modal";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { stepUpFetch } from "@/lib/admin-step-up";
import { formatDateTime } from "@/lib/utils/format";
import type { AuthEventRow, AuthOutcome, ResolvedSubject } from "@/types/admin-security";

const PAGE_SIZE = 50;
const OUTCOMES = ["all", "success", "failure", "blocked", "challenged", "info"] as const;
type OutcomeFilter = (typeof OUTCOMES)[number];

// Feste Liste wie backend app/auth_security/events.py::EVENT_TYPES (technische Codes, keine UI-Texte).
export const AUTH_EVENT_TYPES = [
  "login.password", "login.locked", "login.challenge", "login.mfa.totp", "login.mfa.passkey", "login.success",
  "mfa.enroll", "mfa.remove", "mfa.setup_skipped", "session.revoke", "session.logout", "reset.request", "reset.complete",
  "password.change", "token.invalid", "block.set", "block.clear", "device.revoke", "stepup.success", "stepup.failure",
  "stepup.required", "ratelimit.backend_error", "admin.login.password", "admin.login.mfa", "admin.login.success",
  "admin.mfa.enroll", "admin.mfa.remove", "admin.stepup", "admin.logout",
] as const;

const ACTOR_KINDS = new Set(["user", "admin", "anonymous", "system"]);

export const OUTCOME_BADGE: Record<AuthOutcome, BadgeVariant> = {
  success: "success",
  failure: "danger",
  blocked: "warning",
  challenged: "info",
  info: "neutral",
};

/** /admin/security/events: Filter (Ergebnis, Typ) und Seite stehen in der URL - nur Codes und Zahlen,
 * keine Personendaten. Die Antwort hat keine Gesamtzahl, daher Blättern mit «Neuere/Ältere». */
export function SecurityEvents() {
  const t = useTranslations("adminSecurity");
  const locale = useLocale();
  const router = useRouter();
  const params = useSearchParams();
  const outcomeParam = params.get("outcome") ?? "all";
  const outcome: OutcomeFilter = (OUTCOMES as readonly string[]).includes(outcomeParam) ? (outcomeParam as OutcomeFilter) : "all";
  const typeParam = params.get("type");
  const eventType = typeParam && (AUTH_EVENT_TYPES as readonly string[]).includes(typeParam) ? typeParam : null;
  const offset = Math.max(0, Number.parseInt(params.get("offset") ?? "0", 10) || 0);

  const path = useMemo(() => {
    const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (outcome !== "all") query.set("outcome", outcome);
    if (eventType) query.set("event_type", eventType);
    return `/api/admin/auth-security/events?${query.toString()}`;
  }, [outcome, eventType, offset]);
  const events = useAdminResource<AuthEventRow[]>(path);
  const confirm = useConfirm();
  const showToast = useToast();
  const [resolved, setResolved] = useState<ResolvedSubject | null>(null);

  // Pseudonym einem Konto zuordnen (1.5.1): nur nach Rückfrage, mit Passkey-Bestätigung und auditiert.
  async function resolveSubject(event: AuthEventRow) {
    const ok = await confirm({ message: t("events.resolveConfirm"), confirmLabel: t("events.resolve") });
    if (!ok) return;
    try {
      setResolved(await stepUpFetch<ResolvedSubject>("security-resolve", `/api/admin/auth-security/events/${encodeURIComponent(event.event_id)}/resolve-subject`, { method: "POST" }));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("loadFailed"), "error");
    }
  }

  function update(next: { outcome?: OutcomeFilter; type?: string | null; offset?: number }) {
    const query = new URLSearchParams();
    const nextOutcome = next.outcome ?? outcome;
    const nextType = next.type === undefined ? eventType : next.type;
    const nextOffset = next.offset ?? 0;
    if (nextOutcome !== "all") query.set("outcome", nextOutcome);
    if (nextType) query.set("type", nextType);
    if (nextOffset > 0) query.set("offset", String(nextOffset));
    const search = query.toString();
    router.replace(`/admin/security/events${search ? `?${search}` : ""}` as Route, { scroll: false });
  }

  if (events.forbidden) return <StatusBanner tone="neutral" message={t("ownerOnly")} />;
  const rows = events.data ?? [];

  return (
    <section className="card section-stack">
      {events.failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}
      <div className="list-filter-row">
        <FilterTabs
          options={OUTCOMES.map((value) => ({ value, label: t(`outcomes.${value}`) }))}
          value={outcome}
          onChange={(value) => update({ outcome: value })}
        />
        <label className="field-stack admin-security-type-filter">
          <span className="field-label">{t("events.typeLabel")}</span>
          <SearchableSelect
            options={[...AUTH_EVENT_TYPES]}
            getId={(item) => item}
            getLabel={(item) => item}
            value={eventType}
            onChange={(item) => update({ type: item ?? null })}
            nullLabel={t("events.typeAll")}
          />
        </label>
      </div>
      <DataTable
        columns={[
          t("events.columns.time"), t("events.columns.type"), t("events.columns.outcome"), t("events.columns.actor"),
          t("events.columns.tenant"), t("events.columns.subject"), t("events.columns.network"), t("events.columns.risk"), t("events.columns.client"),
          t("events.columns.actions"),
        ]}
        emptyMessage={events.loading ? undefined : t("events.empty")}
      >
        {rows.map((event) => (
          <tr key={event.event_id}>
            <td>{formatDateTime(event.ts, locale)}</td>
            <td><code>{event.event_type}</code></td>
            <td><Badge variant={OUTCOME_BADGE[event.outcome] ?? "neutral"} dot>{t(`outcomes.${event.outcome}`)}</Badge></td>
            <td>{ACTOR_KINDS.has(event.actor_kind) ? t(`events.actorKinds.${event.actor_kind}`) : event.actor_kind}</td>
            <td>{event.tenant_id ?? null}</td>
            <td>{event.subject_hash ? <code>{event.subject_hash}</code> : null}</td>
            <td>{event.src_net_hash ? <code>{event.src_net_hash}</code> : null}</td>
            <td>{event.risk_score ?? null}</td>
            <td>{event.user_agent_family ?? null}</td>
            <td>
              {event.subject_hash || event.actor_user_id || event.platform_admin_id ? (
                <button type="button" className="button-secondary" onClick={() => void resolveSubject(event)}>
                  {t("events.resolve")}
                </button>
              ) : null}
            </td>
          </tr>
        ))}
      </DataTable>
      <SubjectModal subject={resolved} onClose={() => setResolved(null)} />
      <div className="admin-security-pager">
        <button type="button" className="button-secondary" disabled={offset === 0} onClick={() => update({ offset: Math.max(0, offset - PAGE_SIZE) })}>
          {t("events.previous")}
        </button>
        <span className="muted">{rows.length > 0 ? t("events.pageInfo", { from: offset + 1, to: offset + rows.length }) : null}</span>
        <button type="button" className="button-secondary" disabled={rows.length < PAGE_SIZE} onClick={() => update({ offset: offset + PAGE_SIZE })}>
          {t("events.next")}
        </button>
      </div>
    </section>
  );
}

function SubjectModal({ subject, onClose }: { subject: ResolvedSubject | null; onClose: () => void }) {
  const t = useTranslations("adminSecurity.subject");
  return (
    <Modal open={subject !== null} onClose={onClose} title={t("title")} description={t("description")}>
      {subject ? (
        subject.kind === "unknown" ? (
          <StatusBanner tone="neutral" message={t("unknown")} />
        ) : (
          <dl className="admin-key-value">
            <div>
              <dt>{t("kind")}</dt>
              <dd>{t(`kinds.${subject.kind}`)}</dd>
            </div>
            <div>
              <dt>{t("name")}</dt>
              <dd>{subject.display_name ?? "—"}</dd>
            </div>
            <div>
              <dt>{t("email")}</dt>
              <dd>{subject.email ?? "—"}</dd>
            </div>
            {subject.kind === "user" ? (
              <div>
                <dt>{t("tenant")}</dt>
                <dd>
                  {subject.tenant_id ? (
                    <Link href={`/admin/tenants/${subject.tenant_id}` as Route}>{subject.tenant_name ?? subject.tenant_id}</Link>
                  ) : "—"}
                </dd>
              </div>
            ) : null}
            <div>
              <dt>{t("via")}</dt>
              <dd>{t(`viaKinds.${subject.via}`)}</dd>
            </div>
          </dl>
        )
      ) : null}
    </Modal>
  );
}
