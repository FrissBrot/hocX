"use client";

import Link from "next/link";
import type { Route } from "next";
import { useId, useState, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { PillMenu } from "@/components/ui/pill-menu";
import { Select } from "@/components/ui/select";
import { StatusBanner } from "@/components/ui/status-banner";
import { DurationField } from "@/components/admin/security/security-blocks";
import { useAdminResource } from "@/components/admin/security/use-admin-resource";
import { useToast } from "@/contexts/toast-context";
import { stepUpFetch } from "@/lib/admin-step-up";
import { parseBlockMinutes } from "@/lib/admin/security-blocks";
import {
  INCIDENT_STATUSES,
  durationParts,
  incidentLabel,
  isOpenStatus,
  severityVariant,
  statusVariant,
} from "@/lib/admin/security-incidents";
import { countryName } from "@/lib/utils/country";
import { formatDateTime } from "@/lib/utils/format";
import type { IncidentActivity, IncidentStatus, IncidentTimelineEvent, SecurityIncident, SecurityIncidentDetail } from "@/types/admin-security";

const KNOWN_RULES = new Set(["stuffing", "spraying", "account_attack", "admin_mfa", "admin_new_device", "blocks", "network", "cross_tenant", "tenant", "limiter"]);
const STAGES = [1, 2, 3, 4, 5] as const;
const MAX_MINUTES = 30 * 24 * 60;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function useRuleTitle() {
  const t = useTranslations("adminSecurity");
  return (rule: string) => t(`alerts.rules.${KNOWN_RULES.has(rule) ? rule : "unknown"}`);
}

/** Betroffen: Netz/Konto als gekürztes Pseudonym, Admin/Mandant mit Namen (nur owner sieht Vorfälle). */
export function useAffectedLabel() {
  const t = useTranslations("adminSecurity.incidents.affected");
  return (incident: Pick<SecurityIncident, "rule" | "subject" | "subject_label" | "tenant">) => {
    if (!incident.subject) return t("platform");
    if (["spraying", "network", "cross_tenant"].includes(incident.rule)) return t("net", { subject: incident.subject });
    if (incident.rule === "account_attack") return t("account", { subject: incident.subject });
    if (incident.rule === "tenant") return t("tenant", { name: incident.tenant?.name ?? incident.subject_label ?? `#${incident.subject}` });
    if (incident.rule === "admin_mfa" || incident.rule === "admin_new_device") return t("admin", { name: incident.subject_label ?? `#${incident.subject}` });
    return incident.subject;
  };
}

export function useDurationText() {
  const t = useTranslations("adminSecurity.incidents.duration");
  return (seconds: number | null) => {
    if (seconds === null) return "–"; // i18n-ok: Platzhalter ohne Text
    const parts = durationParts(seconds);
    if (parts.days > 0) return t("days", { days: parts.days, hours: parts.hours });
    if (parts.hours > 0) return t("hours", { hours: parts.hours, minutes: parts.minutes });
    return t("minutes", { minutes: parts.minutes });
  };
}

function eventsHref(detail: SecurityIncidentDetail): string {
  const params = new URLSearchParams({ range: "14d" });
  for (const [key, value] of Object.entries(detail.event_filter)) if (value) params.set(key, value);
  return `/admin/security/events?${params.toString()}`;
}

/**
 * Vorfall im Detail (Drawer der Vorfall-Seite und Panel im Lagebild): Status, Zuständig, Fakten,
 * Zeitleiste, Beteiligte, Gründe, Abwehrstufe, Notizen und Netzsperre. Jede Änderung mit Passkey.
 */
export function SecurityIncidentDetailView({
  incidentId,
  variant,
  onClose,
  onChanged,
}: {
  incidentId: number;
  variant: "drawer" | "panel";
  onClose?: () => void;
  onChanged?: () => void;
}) {
  const t = useTranslations("adminSecurity.incidents");
  const tRoot = useTranslations("adminSecurity");
  const locale = useLocale();
  const showToast = useToast();
  const headingId = useId();
  const ruleTitle = useRuleTitle();
  const affected = useAffectedLabel();
  const durationText = useDurationText();
  const resource = useAdminResource<SecurityIncidentDetail>(`/api/admin/auth-security/incidents/${incidentId}`);
  const [busy, setBusy] = useState(false);
  const [closing, setClosing] = useState<IncidentStatus | null>(null);
  const [blockOpen, setBlockOpen] = useState(false);
  const [note, setNote] = useState("");
  const detail = resource.data;

  async function mutate(path: string, body: unknown, success: string, purpose: "security-incident" | "security-block" = "security-incident") {
    setBusy(true);
    try {
      await stepUpFetch(purpose, `/api/admin/auth-security/incidents/${incidentId}/${path}`, { method: "POST", body: JSON.stringify(body) });
      showToast(success, "success");
      resource.reload();
      onChanged?.();
      return true;
    } catch (error) {
      showToast(t("detail.failed", { message: errorMessage(error) }), "error");
      return false;
    } finally {
      setBusy(false);
    }
  }

  function changeStatus(status: IncidentStatus) {
    if (!detail || status === detail.status) return;
    // Abschliessen mit optionaler Begründung (Design: «Begründung in den Notizen»)
    if (!isOpenStatus(status)) {
      setClosing(status);
      return;
    }
    void mutate("status", { status }, t("detail.statusSaved", { status: tRoot(`statuses.${status}`) }));
  }

  const heading = (
    <div className="audit-detail-head admin-incident-head">
      <span className="admin-incident-badges">
        <code className="admin-incident-id">{incidentLabel(incidentId)}</code>
        {detail ? <Badge variant={severityVariant(detail.severity)} dot>{tRoot(`severity.${detail.severity}`)}</Badge> : null}
        {detail ? <Badge variant="neutral">{detail.active ? t("active") : t("cleared")}</Badge> : null}
      </span>
      <span className="admin-incident-head-actions">
        {variant === "drawer" ? (
          <Link href={`/admin/security?incident=${incidentId}` as Route} className="admin-security-inline-link">{t("detail.openInSituation")}</Link>
        ) : (
          <Link href={`/admin/security/incidents?incident=${incidentId}` as Route} className="admin-security-inline-link">{t("detail.openInList")}</Link>
        )}
        {onClose ? (
          <button type="button" className="button-icon" aria-label={t("detail.close")} title={t("detail.close")} onClick={onClose}>✕</button>
        ) : null}
      </span>
    </div>
  );

  if (resource.failed || resource.forbidden) {
    return (
      <aside className="audit-detail card admin-security-drawer" aria-label={incidentLabel(incidentId)}>
        {heading}
        <StatusBanner tone={resource.forbidden ? "neutral" : "error"} message={resource.forbidden ? tRoot("ownerOnly") : tRoot("loadFailed")} />
      </aside>
    );
  }

  const open = detail ? isOpenStatus(detail.status) : false;
  const takeOverPossible = detail ? open && detail.assignee?.id !== detail.me : false;
  const acknowledged = detail?.acknowledged_at ? (new Date(detail.acknowledged_at).getTime() - new Date(detail.first_seen_at).getTime()) / 1000 : null;
  const closedAfter = detail?.closed_at ? (new Date(detail.closed_at).getTime() - new Date(detail.first_seen_at).getTime()) / 1000 : null;

  return (
    <aside
      className={`audit-detail card admin-security-drawer admin-incident-detail admin-incident-detail-${variant}`}
      aria-labelledby={headingId}
      onKeyDown={(keyEvent) => { if (keyEvent.key === "Escape" && onClose) onClose(); }}
    >
      {heading}
      {!detail ? <p className="muted">{resource.loading ? t("detail.loading") : null}</p> : (
        <>
          <h2 id={headingId} className="section-title">{ruleTitle(detail.rule)}</h2>
          <p className="muted">
            {affected(detail)} · {t("detail.window", { start: formatDateTime(detail.window.start, locale), end: formatDateTime(detail.window.end, locale) })}
          </p>

          <div className="admin-incident-controls">
            <div className="field-stack" role="group" aria-label={t("detail.statusLabel")}>
              <span className="field-label" aria-hidden="true">{t("detail.statusLabel")}</span>
              <PillMenu
                value={detail.status}
                options={INCIDENT_STATUSES.map((status) => ({ value: status, label: tRoot(`statuses.${status}`), variant: statusVariant(status) }))}
                onChange={changeStatus}
              />
            </div>
            <label className="field-stack admin-incident-assignee">
              <span className="field-label">{t("detail.assigneeLabel")}</span>
              <Select
                value={detail.assignee?.id ?? ""}
                disabled={busy || !open}
                onChange={(event) => {
                  const value = event.target.value || null;
                  void mutate("assign", { admin_id: value }, t("detail.assigned"));
                }}
              >
                <option value="">{t("nobody")}</option>
                {detail.assignees.map((admin) => <option key={admin.id} value={admin.id}>{admin.name}</option>)}
              </Select>
            </label>
            {takeOverPossible ? (
              <button type="button" className="button-primary" disabled={busy} onClick={() => void mutate("assign", { admin_id: detail.me }, t("detail.takenOver"))}>
                {t("detail.takeOver")}
              </button>
            ) : null}
          </div>
          <p className="field-help">{t("detail.passkeyHint")}</p>

          <dl className="admin-incident-facts">
            {(["failures", "accounts", "networks", "tenants", "blocked", "successes"] as const).map((key) => (
              <div key={key}><dt>{t(`facts.${key}`)}</dt><dd>{detail.facts[key].toLocaleString(locale)}</dd></div>
            ))}
            <div><dt>{t("facts.maxRisk")}</dt><dd>{detail.max_risk ?? "–"}</dd></div>
            <div><dt>{t("facts.untilTakeover")}</dt><dd>{durationText(acknowledged)}</dd></div>
            <div><dt>{t("facts.untilClosed")}</dt><dd>{durationText(closedAfter)}</dd></div>
            <div><dt>{t("facts.triggers")}</dt><dd>{detail.trigger_count}</dd></div>
          </dl>

          <IncidentTimeline detail={detail} />

          <section className="audit-detail-section" aria-labelledby={`${headingId}-participants`}>
            <h3 id={`${headingId}-participants`} className="audit-detail-title">{t("detail.participantsTitle")}</h3>
            <p className="field-help">{t("detail.participantsHint")}</p>
            <Participants detail={detail} />
          </section>

          <section className="audit-detail-section" aria-labelledby={`${headingId}-reasons`}>
            <h3 id={`${headingId}-reasons`} className="audit-detail-title">{t("detail.reasonsTitle")}</h3>
            {detail.reasons.length === 0 ? <p className="muted">{t("detail.noReasons")}</p> : (
              <ul className="admin-security-reason-list">
                {detail.reasons.map((reason) => (
                  <li key={reason.code}>
                    <span>{tRoot.has(`events.reasons.${reason.code}`) ? tRoot(`events.reasons.${reason.code}`) : reason.code}</span>
                    <span className="muted">{t("detail.reasonCount", { count: reason.count })}</span>
                    <span className="admin-security-mono">{reason.weight !== null ? `+${reason.weight}` : null}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="audit-detail-section" aria-labelledby={`${headingId}-stage`}>
            <h3 id={`${headingId}-stage`} className="audit-detail-title">{t("detail.stageTitle")}</h3>
            <ol className="admin-incident-stages" aria-label={detail.stage ? t("detail.stageReached", { stage: detail.stage }) : t("detail.stageNone")}>
              {STAGES.map((stage) => (
                <li key={stage} className={`admin-incident-stage${stage <= detail.stage ? " admin-incident-stage-reached" : ""}${stage === detail.stage ? " admin-incident-stage-current" : ""}`}>
                  <span className="admin-incident-stage-bar" aria-hidden="true" />
                  <span>{t(`stages.${stage}`)}</span>
                </li>
              ))}
            </ol>
          </section>

          <section className="audit-detail-section" aria-labelledby={`${headingId}-notes`}>
            <h3 id={`${headingId}-notes`} className="audit-detail-title">{t("detail.notesTitle")}</h3>
            {detail.notes.length === 0 ? <p className="muted">{t("detail.notesEmpty")}</p> : (
              <ul className="admin-incident-notes">
                {detail.notes.map((item) => (
                  <li key={item.id}>
                    <span className="muted">{t("detail.noteMeta", { name: item.admin ?? t("detail.unknownAdmin"), time: formatDateTime(item.at, locale) })}</span>
                    <span>{item.note}</span>
                  </li>
                ))}
              </ul>
            )}
            <ModalSaveForm
              className="section-stack"
              onSubmit={async (event) => {
                event.preventDefault();
                if (!note.trim()) return;
                if (await mutate("notes", { note: note.trim() }, t("detail.noteSaved"))) setNote("");
              }}
            >
              <label className="field-stack">
                <span className="field-label">{t("detail.noteLabel")}</span>
                <textarea value={note} onChange={(event) => setNote(event.target.value)} maxLength={1000} rows={2} />
                <span className="field-help">{t("detail.noteHelp")}</span>
              </label>
              <div className="admin-security-block-actions">
                <button type="submit" className="button-secondary" disabled={busy || !note.trim()}>{t("detail.noteSave")}</button>
              </div>
            </ModalSaveForm>
          </section>

          <div className="admin-security-block-actions">
            <Link href={eventsHref(detail) as Route} className="button-secondary button-ghost">{t("detail.allEvents")}</Link>
            {detail.can_block ? (
              <button type="button" className="button-danger" onClick={() => setBlockOpen(true)}>{t("detail.blockAction")}</button>
            ) : null}
          </div>

          <CloseIncidentModal
            status={closing}
            busy={busy}
            onClose={() => setClosing(null)}
            onSubmit={async (status, reason) => {
              const ok = await mutate("status", reason ? { status, note: reason } : { status }, t("detail.statusSaved", { status: tRoot(`statuses.${status}`) }));
              if (ok) setClosing(null);
            }}
          />
          <BlockNetworkModal
            open={blockOpen}
            net={detail.subject ?? ""}
            busy={busy}
            onClose={() => setBlockOpen(false)}
            onSubmit={async (minutes, reason) => {
              const ok = await mutate("block", { minutes, reason }, t("detail.blocked"), "security-block");
              if (ok) setBlockOpen(false);
            }}
          />
        </>
      )}
    </aside>
  );
}

function IncidentTimeline({ detail }: { detail: SecurityIncidentDetail }) {
  const t = useTranslations("adminSecurity.incidents.timeline");
  const tRoot = useTranslations("adminSecurity");
  const locale = useLocale();

  function activityText(item: IncidentActivity): string {
    const status = (value: string | null) => (value && tRoot.has(`statuses.${value}`) ? tRoot(`statuses.${value}`) : value ?? "");
    const severity = (value: string | null) => (value && tRoot.has(`severity.${value}`) ? tRoot(`severity.${value}`) : value ?? "");
    switch (item.type) {
      case "status":
        return t("status", { from: status(item.from), to: status(item.to) });
      case "assigned":
        return item.to ? t("assigned", { name: item.to }) : t("unassigned");
      case "escalated":
        return t("escalated", { to: severity(item.to) });
      case "block":
        return t("block", { net: item.to ?? "" });
      default:
        return t(item.type);
    }
  }

  function eventText(item: IncidentTimelineEvent): string {
    const base = item.marker === "first" ? t("eventFirst") : item.marker === "last" ? t("eventLast") : t("event");
    return `${base}: ${item.event_type} · ${tRoot.has(`outcomes.${item.outcome}`) ? tRoot(`outcomes.${item.outcome}`) : item.outcome}`;
  }

  return (
    <section className="audit-detail-section">
      <h3 className="audit-detail-title">{t("title")}</h3>
      <ol className="admin-incident-timeline">
        {detail.timeline.map((item) => {
          const kind = item.kind === "event"
            ? (item.outcome === "failure" ? "failure" : item.outcome === "success" ? "success" : item.event_type.startsWith("block.") ? "auto" : "event")
            : item.admin ? "person" : "rule";
          return (
            <li key={item.kind === "event" ? item.event_id : `a${item.id}`} className={`admin-incident-timeline-item admin-incident-kind-${kind}`}>
              <span className="admin-incident-timeline-time">{formatDateTime(item.at, locale)}</span>
              <span className="admin-incident-timeline-dot" aria-hidden="true" />
              <span className="admin-incident-timeline-body">
                <span className="admin-incident-timeline-kind">{t(`kinds.${kind}`)}</span>
                <span>{item.kind === "event" ? eventText(item) : activityText(item)}</span>
                {item.kind === "event" ? (
                  <span className="muted admin-security-mono">
                    {[item.subject ? t("account", { value: item.subject }) : null, item.net ? t("net", { value: item.net }) : null,
                      item.country ? countryName(item.country, locale) : null, item.risk_score !== null ? t("risk", { score: item.risk_score }) : null,
                      item.stage ? t("stage", { stage: item.stage }) : null].filter(Boolean).join(" · ")}
                  </span>
                ) : item.admin ? <span className="muted">{item.admin}</span> : null}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function Participants({ detail }: { detail: SecurityIncidentDetail }) {
  const t = useTranslations("adminSecurity.incidents.participants");
  const locale = useLocale();
  const columns = [t("value"), t("failures"), t("events")];
  const groups: { key: string; title: string; rows: { key: string; label: ReactNode; failures: number; events: number }[] }[] = [
    { key: "networks", title: t("networks"), rows: detail.participants.networks.map((row) => ({ key: row.key, label: <code>{row.key}</code>, failures: row.failures, events: row.events })) },
    { key: "accounts", title: t("accounts"), rows: detail.participants.accounts.map((row) => ({ key: row.key, label: <code>{row.key}</code>, failures: row.failures, events: row.events })) },
    {
      key: "tenants", title: t("tenants"),
      rows: detail.participants.tenants.map((row) => ({
        key: row.id, label: <Link href={`/admin/tenants/${row.id}` as Route} className="admin-security-inline-link">{row.name}</Link>, failures: row.failures, events: row.events,
      })),
    },
    { key: "countries", title: t("countries"), rows: detail.participants.countries.map((row) => ({ key: row.code, label: countryName(row.code, locale) ?? row.code, failures: row.failures, events: row.events })) },
  ];
  const visible = groups.filter((group) => group.rows.length > 0);
  if (visible.length === 0) return <p className="muted">{t("empty")}</p>;
  return (
    <div className="admin-incident-participants">
      {visible.map((group) => (
        <div key={group.key} className="admin-incident-participant-group">
          <h4 className="field-label">{group.title}</h4>
          <DataTable columns={columns}>
            {group.rows.map((row) => (
              <tr key={row.key}>
                <td>{row.label}</td>
                <td>{row.failures.toLocaleString(locale)}</td>
                <td>{row.events.toLocaleString(locale)}</td>
              </tr>
            ))}
          </DataTable>
        </div>
      ))}
    </div>
  );
}

function CloseIncidentModal({
  status, busy, onClose, onSubmit,
}: {
  status: IncidentStatus | null;
  busy: boolean;
  onClose: () => void;
  onSubmit: (status: IncidentStatus, reason: string | null) => Promise<void>;
}) {
  const t = useTranslations("adminSecurity.incidents.detail");
  const tRoot = useTranslations("adminSecurity");
  const [reason, setReason] = useState("");
  return (
    <Modal open={status !== null} title={t("closeTitle", { status: status ? tRoot(`statuses.${status}`) : "" })} description={t("closeDescription")} onClose={onClose}>
      <ModalSaveForm
        className="section-stack"
        onSubmit={async (event) => {
          event.preventDefault();
          if (!status) return;
          await onSubmit(status, reason.trim() || null);
          setReason("");
        }}
      >
        <label className="field-stack">
          <span className="field-label">{t("closeReasonLabel")}</span>
          <textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={1000} rows={3} />
          <span className="field-help">{t("noteHelp")}</span>
        </label>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{t("cancel")}</button>
          <button type="submit" className="button-primary" disabled={busy}>{t("closeSave")}</button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}

function BlockNetworkModal({
  open, net, busy, onClose, onSubmit,
}: {
  open: boolean;
  net: string;
  busy: boolean;
  onClose: () => void;
  onSubmit: (minutes: number, reason: string) => Promise<void>;
}) {
  const t = useTranslations("adminSecurity.incidents.detail");
  const tBlocks = useTranslations("adminSecurity.blocks");
  const [preset, setPreset] = useState("60");
  const [custom, setCustom] = useState("");
  const [reason, setReason] = useState("");
  const minutes = parseBlockMinutes(preset, custom, MAX_MINUTES);
  const valid = reason.trim().length > 2 && minutes !== null;
  return (
    <Modal open={open} title={t("blockTitle", { net })} description={t("blockDescription")} onClose={onClose}>
      <ModalSaveForm
        className="section-stack"
        onSubmit={async (event) => {
          event.preventDefault();
          if (!valid || minutes === null) return;
          await onSubmit(minutes, reason.trim());
          setReason("");
        }}
      >
        <DurationField preset={preset} custom={custom} onPreset={setPreset} onCustom={setCustom} />
        <label className="field-stack">
          <span className="field-label">{tBlocks("reasonLabel")}</span>
          <input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={200} required />
          <span className="field-help">{tBlocks("reasonHelp")}</span>
        </label>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{tBlocks("cancel")}</button>
          <button type="submit" className="button-primary" disabled={!valid || busy}>{tBlocks("save")}</button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}
