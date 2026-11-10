"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ActionMenu } from "@/components/ui/action-menu";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { locales } from "@/i18n/locale-config.generated";
import { formatDate, formatDateTime, formatTime, toIntlLocale } from "@/lib/utils/format";
import { MaintenanceCondition, MaintenanceOverview, MaintenanceState, MaintenanceWindow } from "@/types/api";

type TFunc = ReturnType<typeof useTranslations>;

const ACTIVE_POLL_MS = 10_000;
const IDLE_POLL_MS = 30_000;
// Anmeldeseite der Anwendung (dort erscheint der Wartungshinweis)
const LOGIN_PATH = "/login";

export const MAINTENANCE_STATE_VARIANTS: Record<MaintenanceState, BadgeVariant> = {
  scheduled: "info",
  preparing: "warning",
  active: "warning",
  verifying: "info",
  completed: "success",
  failed: "danger",
  overdue: "danger",
  cancelled: "neutral",
};

/** Dauer grob in Minuten/Stunden - keine Scheingenauigkeit. */
export function formatDuration(seconds: number | null | undefined, t: TFunc): string {
  if (seconds === null || seconds === undefined) return "—";
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 120) return t("duration.minutes", { count: minutes });
  return t("duration.hours", { count: Math.round(minutes / 60) });
}

/** Laufzeituhr HH:MM:SS (zählt über 24 h weiter). */
export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(Math.floor(total / 3600))}:${pad(Math.floor((total % 3600) / 60))}:${pad(total % 60)}`;
}

function combine(date: string, time: string): string | null {
  if (!date) return null;
  const match = /^(\d{1,2}):(\d{2})$/.exec(time.trim() || "00:00");
  if (!match) return null;
  const local = new Date(`${date}T${match[1].padStart(2, "0")}:${match[2]}:00`);
  return Number.isNaN(local.getTime()) ? null : local.toISOString();
}

function seconds(from: string | null, to: string | null): number | null {
  if (!from || !to) return null;
  return (new Date(to).getTime() - new Date(from).getTime()) / 1000;
}

function sameDay(a: string, b: string): boolean {
  return new Date(a).toDateString() === new Date(b).toDateString();
}

/** "03.10.2026, 22:00 – 22:41" bzw. mit vollem Ende, wenn es an einem anderen Tag liegt. */
function formatRange(start: string | null, end: string | null, locale: string): string {
  if (!start) return "—";
  if (!end) return formatDateTime(start, locale);
  return `${formatDateTime(start, locale)} – ${sameDay(start, end) ? formatTime(end, locale) : formatDateTime(end, locale)}`;
}

function kindKey(window: MaintenanceWindow): "full" | "writes" | "uploads" {
  return window.kind === "full" ? "full" : window.block_scope === "uploads" ? "uploads" : "writes";
}

function messageOf(window: MaintenanceWindow, locale: string): string | null {
  return window.public_message[locale] || window.public_message.de || null;
}

/** "in 7 Tagen" / "in 5 Stunden" / "in 20 Minuten" bis zum geplanten Beginn. */
function countdown(start: string | null, now: number, t: TFunc): string | null {
  if (!start) return null;
  const minutes = Math.round((new Date(start).getTime() - now) / 60_000);
  if (minutes <= 0) return t("countdown.due");
  if (minutes < 120) return t("countdown.minutes", { count: minutes });
  if (minutes < 48 * 60) return t("countdown.hours", { count: Math.round(minutes / 60) });
  return t("countdown.days", { count: Math.round(minutes / (60 * 24)) });
}

type Props = { initialOverview: MaintenanceOverview };

export function AdminMaintenance({ initialOverview }: Props) {
  const t = useTranslations("adminMaintenance");
  const locale = useLocale();
  const showToast = useToast();
  const confirm = useConfirm();
  const [overview, setOverview] = useState(initialOverview);
  const [planning, setPlanning] = useState(false);
  const [editing, setEditing] = useState<MaintenanceWindow | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const loadingRef = useRef(false);

  const reload = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    try {
      setOverview(await browserApiFetch<MaintenanceOverview>("/api/admin/maintenance"));
    } catch {
      // Letzten Stand weiter zeigen.
    } finally {
      loadingRef.current = false;
    }
  }, []);

  useEffect(() => {
    const interval = setInterval(() => void reload(), overview.blocking ? ACTIVE_POLL_MS : IDLE_POLL_MS);
    return () => clearInterval(interval);
  }, [overview.blocking, reload]);

  // Laufzeituhr: nur während einer laufenden Wartung sekündlich, sonst minütlich (Countdown).
  const running = overview.current.length > 0;
  useEffect(() => {
    const interval = setInterval(() => setNow(Date.now()), running ? 1000 : 60_000);
    return () => clearInterval(interval);
  }, [running]);

  async function act(window: MaintenanceWindow, action: "release" | "start" | "cancel") {
    const messages = { release: t("confirm.release"), start: t("confirm.start"), cancel: t("confirm.cancel") };
    if (!(await confirm({ message: messages[action], tone: action === "cancel" ? "danger" : "default", confirmLabel: t(`actions.${action}`) }))) return;
    setBusy(`${window.id}:${action}`);
    try {
      await browserApiFetch(`/api/admin/maintenance/${window.id}/${action}`, { method: "POST" });
      showToast(t(`toast.${action}`), "success");
      await reload();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setBusy(null);
    }
  }

  const next = overview.scheduled[0] ?? null;

  return (
    <div className="grid maintenance-page">
      <div className="page-header maintenance-page-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("description")}</p>
        </div>
        <button type="button" className="button-primary" onClick={() => setPlanning(true)}>{t("actions.plan")}</button>
      </div>

      {running ? (
        overview.current.map((window) => (
          <RunningCard
            key={window.id}
            window={window}
            t={t}
            locale={locale}
            now={now}
            busy={busy}
            onRelease={() => void act(window, "release")}
            onStart={() => void act(window, "start")}
            onEdit={() => setEditing(window)}
          />
        ))
      ) : (
        <section className="maintenance-idle">
          <span className="maintenance-idle-dot" aria-hidden="true" />
          <div className="maintenance-idle-text">
            <strong>{t("idle.title")}</strong>
            <span className="muted">
              {next?.scheduled_start_at
                ? t("idle.next", { countdown: countdown(next.scheduled_start_at, now, t) ?? "", start: formatDateTime(next.scheduled_start_at, locale) })
                : t("scheduled.empty")}
            </span>
          </div>
          {next ? (
            <a className="maintenance-link" href={LOGIN_PATH} target="_blank" rel="noreferrer">{t("idle.viewLogin")}</a>
          ) : null}
        </section>
      )}

      <section className="maintenance-section">
        <h2 className="maintenance-section-title">{t("scheduled.title")}</h2>
        {overview.scheduled.length === 0 ? (
          <div className="maintenance-empty">{t("scheduled.empty")}</div>
        ) : (
          overview.scheduled.map((window) => (
            <ScheduledCard
              key={window.id}
              window={window}
              t={t}
              locale={locale}
              now={now}
              busy={busy}
              onStart={() => void act(window, "start")}
              onEdit={() => setEditing(window)}
              onCancel={() => void act(window, "cancel")}
            />
          ))
        )}
      </section>

      <section className="card maintenance-history">
        <h2 className="maintenance-section-title">{t("history.title")}</h2>
        <DataTable columns={[t("columns.reason"), t("columns.state"), t("columns.period"), t("columns.durationEstimate")]} emptyMessage={t("history.empty")}>
          {overview.history.map((window) => {
            const actual = seconds(window.started_at, window.ended_at);
            const planned = seconds(window.started_at, window.original_estimated_end_at);
            const ratio = actual !== null && planned ? actual / planned : null;
            const tone = window.state === "completed" ? (ratio !== null && ratio > 1 ? "over" : "ok") : "neutral";
            return (
              <tr key={window.id}>
                <td className="maintenance-history-reason">{t(`reason.${knownReason(window.reason_code)}`)}</td>
                <td><Badge variant={MAINTENANCE_STATE_VARIANTS[window.state]}>{t(`state.${window.state}`)}</Badge></td>
                <td className="muted">{formatRange(window.started_at, window.ended_at, locale)}</td>
                <td>
                  <div className="maintenance-duration">
                    <span>
                      {formatDuration(actual, t)} <span className="muted">· {formatDuration(planned, t)}</span>
                    </span>
                    {ratio !== null ? (
                      <span className={`maintenance-bar maintenance-bar-${tone}`} aria-hidden="true">
                        <span style={{ width: `${Math.min(100, ratio * 100)}%` }} />
                      </span>
                    ) : null}
                  </div>
                </td>
              </tr>
            );
          })}
        </DataTable>
      </section>

      {planning ? <PlanModal t={t} locale={locale} onClose={() => setPlanning(false)} onSaved={() => { setPlanning(false); void reload(); }} /> : null}
      {editing ? <EditModal t={t} window={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); void reload(); }} /> : null}
    </div>
  );
}

const REASONS = new Set(["manual", "storage_initial_migration", "storage_cutover", "backup_restore"]);

function knownReason(code: string): string {
  return REASONS.has(code) ? code : "other";
}

const CONDITION_REASONS = new Set([
  "ok", "fenced", "cutover_open", "migration_missing", "integrity_not_confirmed", "target_verified", "target_unverified", "source_consistent", "inconsistent",
]);

function conditionDetail(condition: MaintenanceCondition, t: TFunc): string | null {
  if (CONDITION_REASONS.has(condition.reason)) return t(`conditions.reasons.${condition.reason}`);
  if (condition.reason.startsWith("migration_")) return t("conditions.reasons.migration_running");
  return null;
}

function RunningCard({ window, t, locale, now, busy, onRelease, onStart, onEdit }: {
  window: MaintenanceWindow; t: TFunc; locale: string; now: number; busy: string | null; onRelease: () => void; onStart: () => void; onEdit: () => void;
}) {
  const runtime = window.started_at ? (now - new Date(window.started_at).getTime()) / 1000 : null;
  const planned = seconds(window.started_at, window.estimated_end_at);
  const remaining = window.estimated_end_at ? (new Date(window.estimated_end_at).getTime() - now) / 1000 : null;
  const unmet = window.conditions.filter((condition) => !condition.satisfied);
  const total = Number(window.progress.objects_total ?? 0);
  const verified = Number(window.progress.objects_verified ?? 0);
  const copied = Number(window.progress.objects_copied ?? 0);
  const message = messageOf(window, locale);
  const job = window.source_job_type
    ? t(`job.${["storage_initial_migration", "storage_cutover", "backup_restore", "backup_restore_cli"].includes(window.source_job_type) ? window.source_job_type : "other"}`)
    : null;
  return (
    <section className="maintenance-running" aria-label={t("current.title")}>
      <div className="maintenance-running-main">
        <div className="maintenance-running-kicker">
          <span className="maintenance-running-dot" aria-hidden="true" />
          <span>{t("running.kicker", { state: window.state, kind: t(`kindLabel.${kindKey(window)}`) })}</span>
        </div>
        <div className="maintenance-running-clock" aria-label={t("facts.runtime")}>{runtime !== null ? formatClock(runtime) : "—"}</div>
        <div className="maintenance-running-meta">
          {window.started_at ? t("running.started", { time: formatTime(window.started_at, locale) }) : t("running.notStarted")}
          {" · "}
          {window.estimated_end_at
            ? remaining !== null && remaining > 0
              ? t("running.until", { time: formatTime(window.estimated_end_at, locale), remaining: formatDuration(remaining, t) })
              : t("running.overdue", { time: formatTime(window.estimated_end_at, locale) })
            : t("facts.estimating")}
          {job ? ` · ${t("running.job", { job })}` : null}
        </div>
        {runtime !== null && planned ? (
          <span className="maintenance-running-bar" aria-hidden="true">
            <span style={{ width: `${Math.min(100, (runtime / planned) * 100)}%` }} />
          </span>
        ) : null}
        {total > 0 ? (
          <div className="maintenance-running-progress">
            <span>{t("progress.label", { copied, verified, total })}</span>
            <progress className="storage-progress" max={total} value={verified} aria-label={t("progress.aria")} />
          </div>
        ) : null}
        <p className="maintenance-running-message">{message ?? t(`reason.${knownReason(window.reason_code)}`)}</p>
        {window.state === "overdue" ? <StatusBanner tone="error" message={t("banner.overdue")} /> : null}
        {window.last_error ? <StatusBanner tone="error" message={window.last_error} /> : null}
        <div className="maintenance-running-actions">
          {window.state === "preparing" && !window.source_job_type ? (
            <button type="button" className="button-secondary" disabled={busy !== null} onClick={onStart}>{t("actions.start")}</button>
          ) : null}
          <button type="button" className="button-secondary" onClick={onEdit}>{t("actions.editMessage")}</button>
        </div>
      </div>
      <div className="maintenance-checks">
        <h3 className="maintenance-checks-title">{t("conditions.title")}</h3>
        <ul>
          {window.conditions.map((condition) => {
            const detail = conditionDetail(condition, t);
            return (
              <li key={condition.key} className={condition.satisfied ? "maintenance-check-met" : "maintenance-check-unmet"}>
                <span className="maintenance-check-mark" aria-label={condition.satisfied ? t("conditions.met") : t("conditions.unmet")}>
                  {condition.satisfied ? "✓" : "!"} {/* i18n-ok: Symbol, Bedeutung steht im aria-label */}
                </span>
                <div className="maintenance-check-text">
                  <span>{t.has(`conditions.keys.${condition.key}`) ? t(`conditions.keys.${condition.key}`) : condition.key}</span>
                  {detail ? <span className="maintenance-check-detail">{detail}</span> : null}
                </div>
              </li>
            );
          })}
        </ul>
        <button type="button" className="maintenance-release" disabled={busy !== null || unmet.length > 0} onClick={onRelease}>
          {unmet.length > 0 ? t("conditions.blockedHint") : t("actions.release")}
        </button>
      </div>
    </section>
  );
}

function ScheduledCard({ window, t, locale, now, busy, onStart, onEdit, onCancel }: {
  window: MaintenanceWindow; t: TFunc; locale: string; now: number; busy: string | null; onStart: () => void; onEdit: () => void; onCancel: () => void;
}) {
  const start = window.scheduled_start_at;
  const date = start ? new Date(start) : null;
  const intl = toIntlLocale(locale);
  const duration = seconds(start, window.scheduled_end_at);
  const message = messageOf(window, locale);
  return (
    <article className="maintenance-scheduled">
      {date ? (
        <div className="maintenance-date-tile" aria-label={formatDate(start)}>
          <span className="maintenance-date-month">{new Intl.DateTimeFormat(intl, { month: "short" }).format(date).replace(".", "")}</span>
          <span className="maintenance-date-day">{date.getDate()}</span>
          <span className="maintenance-date-weekday">{new Intl.DateTimeFormat(intl, { weekday: "long" }).format(date)}</span>
        </div>
      ) : null}
      <div className="maintenance-scheduled-body">
        <div className="maintenance-scheduled-line">
          <span className="maintenance-scheduled-time">
            {start ? formatTime(start, locale) : "—"}
            {window.scheduled_end_at ? ` – ${sameDay(start ?? window.scheduled_end_at, window.scheduled_end_at) ? formatTime(window.scheduled_end_at, locale) : formatDateTime(window.scheduled_end_at, locale)}` : ""}
          </span>
          {duration ? <span className="muted">{formatDuration(duration, t)}</span> : null}
          <Badge variant="warning">{t(`kindLabel.${kindKey(window)}`)}</Badge>
          <span className="muted">{countdown(start, now, t)}</span>
        </div>
        <p className="maintenance-scheduled-message">{message ? t("quoted", { message }) : t("defaultMessageHint")}</p>
        <span className="muted maintenance-scheduled-meta">
          {window.created_by_email ? t("scheduled.metaBy", { email: window.created_by_email }) : t("scheduled.meta")}
        </span>
      </div>
      <div className="maintenance-scheduled-actions">
        <button type="button" className="button-secondary" disabled={busy !== null} onClick={onStart}>{t("actions.startNow")}</button>
        <button type="button" className="button-secondary" onClick={onEdit}>{t("actions.edit")}</button>
        <ActionMenu
          ariaLabel={t("actions.more")}
          items={[
            { label: t("idle.viewLoginShort"), onClick: () => globalThis.open(LOGIN_PATH, "_blank", "noopener") },
            { label: t("actions.cancelPlanned"), onClick: onCancel, danger: true },
          ]}
        />
      </div>
    </article>
  );
}

type LocalizedMessages = { [locale: string]: string };
type MessageFieldsProps = { t: TFunc; messages: LocalizedMessages; onChange: (next: LocalizedMessages) => void };

function MessageFields({ t, messages, onChange }: MessageFieldsProps) {
  return (
    <>
      {locales.map((code) => (
        <label key={code} className="field-stack">
          <span className="field-label">{t("form.message", { locale: code.toUpperCase() })}</span>
          <textarea className="input" rows={2} maxLength={2000} value={messages[code] ?? ""} onChange={(event) => onChange({ ...messages, [code]: event.target.value })} />
        </label>
      ))}
      <span className="field-help">{t("form.messageHelp")}</span>
    </>
  );
}

type PlanKind = "full" | "writes" | "uploads";

function PlanModal({ t, locale, onClose, onSaved }: { t: TFunc; locale: string; onClose: () => void; onSaved: () => void }) {
  const showToast = useToast();
  const tm = useTranslations("maintenance");
  const [kind, setKind] = useState<PlanKind>("full");
  const [startNow, setStartNow] = useState(false);
  const [startDate, setStartDate] = useState("");
  const [startTime, setStartTime] = useState("");
  const [endDate, setEndDate] = useState("");
  const [endTime, setEndTime] = useState("");
  const [messages, setMessages] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const start = startNow ? null : combine(startDate, startTime);
  const end = endDate ? combine(endDate, endTime) : null;
  const valid = (startNow || start !== null) && (!endDate || end !== null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid) return;
    setSaving(true);
    try {
      await browserApiFetch("/api/admin/maintenance", {
        method: "POST",
        body: JSON.stringify({
          kind: kind === "full" ? "full" : "partial", block_scope: kind === "full" ? "all" : kind, start_now: startNow,
          scheduled_start_at: start, scheduled_end_at: end, public_message: messages, internal_note: note || null,
        }),
      });
      showToast(startNow ? t("toast.started") : t("toast.planned"), "success");
      onSaved();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setSaving(false);
    }
  }

  const previewWhen = startNow
    ? t("preview.now")
    : start
      ? end
        ? t("preview.range", { start: formatDateTime(start, locale), end: sameDay(start, end) ? formatTime(end, locale) : formatDateTime(end, locale) })
        : formatDateTime(start, locale)
      : t("preview.noDate");
  // Ohne eigene Meldung zeigt die Anmeldeseite den Standardtext der manuellen Wartung.
  const previewMessage = messages[locale] || messages.de || tm("reasons.manual");

  return (
    <Modal open title={t("plan.title")} onClose={onClose} size="wide">
      <ModalSaveForm className="maintenance-plan" onSubmit={submit}>
        <div className="maintenance-plan-form grid">
          <p className="muted">{t("plan.description")}</p>
          <div className="field-stack">
            <span className="field-label">{t("form.kind")}</span>
            <div className="maintenance-kind-options" role="radiogroup" aria-label={t("form.kind")}>
              {(["full", "writes", "uploads"] as PlanKind[]).map((option) => (
                <button
                  key={option}
                  type="button"
                  role="radio"
                  aria-checked={kind === option}
                  className={`maintenance-kind-option${kind === option ? " maintenance-kind-option-active" : ""}`}
                  onClick={() => setKind(option)}
                >
                  <strong>{t(`kindLabel.${option}`)}</strong>
                  <span>{t(`kindDescription.${option}`)}</span>
                </button>
              ))}
            </div>
          </div>
          <label className="checkbox-row">
            <input type="checkbox" checked={startNow} onChange={(event) => setStartNow(event.target.checked)} />
            <span>{t("form.startNow")}</span>
          </label>
          {!startNow ? (
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">{t("form.startDate")}</span>
                <DateInput value={startDate} onChange={setStartDate} />
              </label>
              <label className="field-stack">
                <span className="field-label">{t("form.startTime")}</span>
                <input className="input" inputMode="numeric" placeholder="22:00" value={startTime} onChange={(event) => setStartTime(event.target.value)} />
              </label>
            </div>
          ) : null}
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("form.endDate")}</span>
              <DateInput value={endDate} onChange={setEndDate} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("form.endTime")}</span>
              <input className="input" inputMode="numeric" placeholder="23:30" value={endTime} onChange={(event) => setEndTime(event.target.value)} />
            </label>
          </div>
          <span className="field-help">{t("form.endHelp")}</span>
          <MessageFields t={t} messages={messages} onChange={setMessages} />
          <label className="field-stack">
            <span className="field-label">{t("form.note")}</span>
            <input className="input" value={note} maxLength={4000} onChange={(event) => setNote(event.target.value)} />
          </label>
        </div>
        <aside className="maintenance-plan-preview" aria-label={t("preview.title")}>
          <span className="maintenance-eyebrow">{t("preview.title")}</span>
          <div className="maintenance-preview-card">
            <div className="maintenance-login-banner">
              <span className="maintenance-login-banner-kicker">{startNow ? t("preview.kickerRunning") : t("preview.kickerPlanned")}</span>
              <strong>{previewWhen}</strong>
              <span>{previewMessage}</span>
            </div>
            <div className="maintenance-preview-skeleton" aria-hidden="true">
              <span /><span /><span /><span />
            </div>
          </div>
          <p className="muted maintenance-preview-hint">{t(`kindHint.${kind}`)}</p>
        </aside>
        <div className="modal-actions maintenance-plan-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{t("actions.close")}</button>
          <button type="submit" className="button-primary" disabled={!valid || saving}>{startNow ? t("actions.startNow") : t("actions.plan")}</button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}

function EditModal({ t, window, onClose, onSaved }: { t: TFunc; window: MaintenanceWindow; onClose: () => void; onSaved: () => void }) {
  const showToast = useToast();
  const [messages, setMessages] = useState<Record<string, string>>(window.public_message);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      await browserApiFetch(`/api/admin/maintenance/${window.id}`, { method: "PATCH", body: JSON.stringify({ public_message: messages }) });
      showToast(t("toast.saved"), "success");
      onSaved();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open title={t("edit.title")} onClose={onClose} size="wide">
      <ModalSaveForm className="grid" onSubmit={submit}>
        <MessageFields t={t} messages={messages} onChange={setMessages} />
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{t("actions.close")}</button>
          <button type="submit" className="button-primary" disabled={saving}>{t("actions.save")}</button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}
