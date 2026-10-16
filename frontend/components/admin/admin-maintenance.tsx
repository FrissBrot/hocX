"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { locales } from "@/i18n/locale-config.generated";
import { formatDateTime } from "@/lib/utils/format";
import { MaintenanceOverview, MaintenanceState, MaintenanceWindow } from "@/types/api";

type TFunc = ReturnType<typeof useTranslations>;

const ACTIVE_POLL_MS = 10_000;
const IDLE_POLL_MS = 30_000;

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

function combine(date: string, time: string): string | null {
  if (!date) return null;
  const match = /^(\d{1,2}):(\d{2})$/.exec(time.trim() || "00:00");
  if (!match) return null;
  const local = new Date(`${date}T${match[1].padStart(2, "0")}:${match[2]}:00`);
  return Number.isNaN(local.getTime()) ? null : local.toISOString();
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

  let banner = null;
  if (overview.full_active) banner = <StatusBanner tone="error" message={t("banner.fullActive")} />;
  else if (overview.blocking) banner = <StatusBanner tone="neutral" message={t("banner.partialActive")} />;

  return (
    <div className="grid">
      <DataToolbar
        title={t("title")}
        description={t("description")}
        actions={<button type="button" className="button-primary" onClick={() => setPlanning(true)}>{t("actions.plan")}</button>}
      />

      {banner}

      <article className="card">
        <DataToolbar title={t("current.title")} />
        {overview.current.length === 0 ? <p className="muted">{t("current.empty")}</p> : null}
        <div className="grid">
          {overview.current.map((window) => (
            <WindowCard key={window.id} window={window} t={t} locale={locale} busy={busy}
              onRelease={() => void act(window, "release")} onStart={() => void act(window, "start")} onEdit={() => setEditing(window)} />
          ))}
        </div>
      </article>

      <article className="card">
        <DataToolbar title={t("scheduled.title")} />
        <DataTable columns={[t("columns.start"), t("columns.end"), t("columns.kind"), t("columns.message"), t("columns.actions")]} emptyMessage={t("scheduled.empty")}>
          {overview.scheduled.map((window) => (
            <tr key={window.id}>
              <td>{formatDateTime(window.scheduled_start_at, locale)}</td>
              <td>{window.scheduled_end_at ? formatDateTime(window.scheduled_end_at, locale) : "—"}</td>
              <td>{t(`kind.${window.kind}`)}</td>
              <td className="muted">{window.public_message[locale] ?? window.public_message.de ?? t("defaultMessage")}</td>
              <td>
                <div className="table-actions">
                  <button type="button" className="button-secondary" disabled={busy !== null} onClick={() => void act(window, "start")}>{t("actions.startNow")}</button>
                  <button type="button" className="button-secondary" onClick={() => setEditing(window)}>{t("actions.edit")}</button>
                  <button type="button" className="button-danger" disabled={busy !== null} onClick={() => void act(window, "cancel")}>{t("actions.cancel")}</button>
                </div>
              </td>
            </tr>
          ))}
        </DataTable>
      </article>

      <article className="card">
        <DataToolbar title={t("history.title")} />
        <DataTable columns={[t("columns.reason"), t("columns.state"), t("columns.start"), t("columns.end"), t("columns.duration"), t("columns.estimate")]} emptyMessage={t("history.empty")}>
          {overview.history.map((window) => {
            const actual = window.started_at && window.ended_at ? (new Date(window.ended_at).getTime() - new Date(window.started_at).getTime()) / 1000 : null;
            const planned = window.started_at && window.original_estimated_end_at ? (new Date(window.original_estimated_end_at).getTime() - new Date(window.started_at).getTime()) / 1000 : null;
            return (
              <tr key={window.id}>
                <td>{t(`reason.${knownReason(window.reason_code)}`)}</td>
                <td><Badge variant={MAINTENANCE_STATE_VARIANTS[window.state]}>{t(`state.${window.state}`)}</Badge></td>
                <td>{window.started_at ? formatDateTime(window.started_at, locale) : "—"}</td>
                <td>{window.ended_at ? formatDateTime(window.ended_at, locale) : "—"}</td>
                <td>{formatDuration(actual, t)}</td>
                <td className="muted">{formatDuration(planned, t)}</td>
              </tr>
            );
          })}
        </DataTable>
      </article>

      {planning ? <PlanModal t={t} onClose={() => setPlanning(false)} onSaved={() => { setPlanning(false); void reload(); }} /> : null}
      {editing ? <EditModal t={t} window={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); void reload(); }} /> : null}
    </div>
  );
}

const REASONS = new Set(["manual", "storage_initial_migration", "storage_cutover"]);

function knownReason(code: string): string {
  return REASONS.has(code) ? code : "other";
}

function WindowCard({ window, t, locale, busy, onRelease, onStart, onEdit }: {
  window: MaintenanceWindow; t: TFunc; locale: string; busy: string | null; onRelease: () => void; onStart: () => void; onEdit: () => void;
}) {
  const runtime = window.started_at ? (Date.now() - new Date(window.started_at).getTime()) / 1000 : null;
  const unmet = window.conditions.filter((condition) => !condition.satisfied);
  const total = Number(window.progress.objects_total ?? 0);
  const verified = Number(window.progress.objects_verified ?? 0);
  const copied = Number(window.progress.objects_copied ?? 0);
  return (
    <section className="maintenance-admin-card">
      <div className="maintenance-admin-head">
        <Badge variant={MAINTENANCE_STATE_VARIANTS[window.state]} dot>{t(`state.${window.state}`)}</Badge>
        <strong>{t(`reason.${knownReason(window.reason_code)}`)}</strong>
        <span className="muted">{window.kind === "full" ? t("kind.full") : t(`scope.${window.block_scope}`)}</span>
      </div>
      <dl className="maintenance-admin-facts">
        <dt>{t("facts.job")}</dt>
        <dd>{window.source_job_type ? t(`job.${window.source_job_type === "storage_initial_migration" || window.source_job_type === "storage_cutover" ? window.source_job_type : "other"}`) : t("job.manual")}</dd>
        <dt>{t("facts.started")}</dt>
        <dd>{window.started_at ? formatDateTime(window.started_at, locale) : "—"}</dd>
        <dt>{t("facts.runtime")}</dt>
        <dd>{formatDuration(runtime, t)}</dd>
        <dt>{t("facts.estimatedEnd")}</dt>
        <dd>{window.estimated_end_at ? formatDateTime(window.estimated_end_at, locale) : t("facts.estimating")}</dd>
        <dt>{t("facts.originalEnd")}</dt>
        <dd>{window.original_estimated_end_at ? formatDateTime(window.original_estimated_end_at, locale) : "—"}</dd>
        <dt>{t("facts.reserve")}</dt>
        <dd>{formatDuration(window.safety_margin_seconds, t)}</dd>
        <dt>{t("facts.features")}</dt>
        <dd>{window.affected_features.length ? window.affected_features.map((feature) => t(`feature.${feature}`)).join(", ") : "—"}</dd>
      </dl>
      {total > 0 ? (
        <div className="maintenance-admin-progress">
          <span className="muted">{t("progress.label", { copied, verified, total })}</span>
          <progress className="storage-progress" max={total} value={verified} aria-label={t("progress.aria")} />
        </div>
      ) : null}
      {window.state === "overdue" ? <StatusBanner tone="error" message={t("banner.overdue")} /> : null}
      {window.last_error ? <StatusBanner tone="error" message={window.last_error} /> : null}
      {window.conditions.length ? (
        <ul className="maintenance-admin-conditions" aria-label={t("conditions.title")}>
          {window.conditions.map((condition) => (
            <li key={condition.key}>
              <Badge variant={condition.satisfied ? "success" : "warning"}>{condition.satisfied ? t("conditions.met") : t("conditions.unmet")}</Badge>
              <span>{t(`conditions.keys.${condition.key}`)}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="table-actions">
        {window.state === "preparing" && !window.source_job_type ? (
          <button type="button" className="button-secondary" disabled={busy !== null} onClick={onStart}>{t("actions.start")}</button>
        ) : null}
        <button type="button" className="button-secondary" onClick={onEdit}>{t("actions.editMessage")}</button>
        <button type="button" className="button-primary" disabled={busy !== null || unmet.length > 0} onClick={onRelease}
          title={unmet.length ? t("conditions.blockedHint") : undefined}>
          {t("actions.release")}
        </button>
      </div>
    </section>
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

function PlanModal({ t, onClose, onSaved }: { t: TFunc; onClose: () => void; onSaved: () => void }) {
  const showToast = useToast();
  const [kind, setKind] = useState<"full" | "partial">("full");
  const [scope, setScope] = useState<"writes" | "uploads">("writes");
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
          kind, block_scope: kind === "full" ? "all" : scope, start_now: startNow, scheduled_start_at: start, scheduled_end_at: end,
          public_message: messages, internal_note: note || null,
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

  return (
    <Modal open title={t("plan.title")} onClose={onClose} size="wide">
      <ModalSaveForm className="grid" onSubmit={submit}>
        <p className="muted">{t("plan.description")}</p>
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">{t("form.kind")}</span>
            <select className="input" value={kind} onChange={(event) => setKind(event.target.value as "full" | "partial")}>
              <option value="full">{t("kind.full")}</option>
              <option value="partial">{t("kind.partial")}</option>
            </select>
          </label>
          {kind === "partial" ? (
            <label className="field-stack">
              <span className="field-label">{t("form.scope")}</span>
              <select className="input" value={scope} onChange={(event) => setScope(event.target.value as "writes" | "uploads")}>
                <option value="writes">{t("scope.writes")}</option>
                <option value="uploads">{t("scope.uploads")}</option>
              </select>
            </label>
          ) : null}
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
              <input className="input" inputMode="numeric" placeholder="14:30" value={startTime} onChange={(event) => setStartTime(event.target.value)} />
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
            <input className="input" inputMode="numeric" placeholder="15:30" value={endTime} onChange={(event) => setEndTime(event.target.value)} />
          </label>
        </div>
        <span className="field-help">{t("form.endHelp")}</span>
        <MessageFields t={t} messages={messages} onChange={setMessages} />
        <label className="field-stack">
          <span className="field-label">{t("form.note")}</span>
          <input className="input" value={note} maxLength={4000} onChange={(event) => setNote(event.target.value)} />
        </label>
        <div className="modal-actions">
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
