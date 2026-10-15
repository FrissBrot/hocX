"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ActionMenu } from "@/components/ui/action-menu";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime, formatFileSize } from "@/lib/utils/format";
import {
  StorageConnectionTest,
  StorageGeneration,
  StorageMigration,
  StorageMigrationState,
  StorageOverview,
  StorageProfile,
  StorageProvider,
} from "@/types/api";

type TFunc = ReturnType<typeof useTranslations>;

const ACTIVE_POLL_MS = 5_000;
const IDLE_POLL_MS = 30_000;
// Ohne Lebenszeichen des Workers seit so vielen Sekunden: deutlich sichtbar warnen.
const HEARTBEAT_STALE_SECONDS = 120;

const MIGRATION_VARIANTS: Record<StorageMigrationState, BadgeVariant> = {
  pending: "neutral", preflight: "info", awaiting_confirmation: "warning", inventory: "info", copying: "info",
  catching_up: "info", verifying: "info", ready_for_cutover: "warning", cutting_over: "warning", observing: "info",
  completed: "success", paused: "neutral", retrying: "warning", failed: "danger", cancelled: "neutral", rollback_required: "danger",
};

const GENERATION_VARIANTS: Record<StorageGeneration["status"], BadgeVariant> = {
  preparing: "info", active: "success", retained: "warning", abandoned: "neutral", purge_requested: "warning", purging: "warning", purged: "neutral",
};

// "garage_local" ist nicht wählbar: das lokale S3-Profil legt das Backend selbst an (LOCAL_S3_*).
const PROVIDERS: StorageProvider[] = ["hetzner", "aws_s3", "s3_compatible"];

function rangeText(t: TFunc, low: number | undefined, high: number | undefined): string {
  if (low === undefined || high === undefined) return t("estimate.unknown");
  const lowMinutes = Math.max(1, Math.ceil(low / 60));
  const highMinutes = Math.max(lowMinutes, Math.ceil(high / 60));
  if (highMinutes >= 120) return t("estimate.hours", { low: Math.max(1, Math.round(lowMinutes / 60)), high: Math.ceil(highMinutes / 60) });
  return t("estimate.minutes", { low: lowMinutes, high: highMinutes });
}

function secondsSince(value: string | null): number | null {
  return value ? Math.max(0, (Date.now() - new Date(value).getTime()) / 1000) : null;
}

export function AdminStorage({ initialOverview }: { initialOverview: StorageOverview }) {
  const t = useTranslations("adminStorage");
  const locale = useLocale();
  const showToast = useToast();
  const confirm = useConfirm();
  const [overview, setOverview] = useState(initialOverview);
  const [history, setHistory] = useState<StorageMigration[]>([]);
  const [editing, setEditing] = useState<StorageProfile | "new" | null>(null);
  const [starting, setStarting] = useState(false);
  const [purging, setPurging] = useState<StorageGeneration | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const loadingRef = useRef(false);

  const reload = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    try {
      const [next, migrations] = await Promise.all([
        browserApiFetch<StorageOverview>("/api/admin/storage/overview"),
        browserApiFetch<StorageMigration[]>("/api/admin/storage/migrations?limit=10"),
      ]);
      setOverview(next);
      setHistory(migrations);
    } catch {
      // Letzten Stand weiter zeigen.
    } finally {
      loadingRef.current = false;
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    const interval = setInterval(() => void reload(), overview.open_migration ? ACTIVE_POLL_MS : IDLE_POLL_MS);
    return () => clearInterval(interval);
  }, [overview.open_migration, reload]);

  async function run(key: string, request: () => Promise<unknown>, success: string) {
    setBusy(key);
    try {
      await request();
      showToast(success, "success");
      await reload();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setBusy(null);
    }
  }

  async function testProfile(profile: StorageProfile) {
    setBusy(`test:${profile.id}`);
    try {
      const result = await browserApiFetch<StorageConnectionTest>(`/api/admin/storage/profiles/${profile.id}/test`, { method: "POST" });
      showToast(result.ok ? t("toast.testOk") : t("toast.testFailed", { error: result.error ?? "" }), result.ok ? "success" : "error");
      await reload();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setBusy(null);
    }
  }

  async function deleteProfile(profile: StorageProfile) {
    if (!(await confirm({ message: t("confirm.deleteProfile", { name: profile.name }), tone: "danger", confirmLabel: t("actions.delete") }))) return;
    await run(`delete:${profile.id}`, () => browserApiFetch(`/api/admin/storage/profiles/${profile.id}`, { method: "DELETE" }), t("toast.deleted"));
  }

  const active = overview.active_profile;
  return (
    <div className="grid">
      <DataToolbar
        title={t("title")}
        description={t("description")}
        actions={
          <>
            <button type="button" className="button-secondary" onClick={() => setEditing("new")}>{t("actions.newProfile")}</button>
            <button type="button" className="button-primary" disabled={overview.open_migration !== null} onClick={() => setStarting(true)}>
              {t("actions.startMigration")}
            </button>
          </>
        }
      />

      {!overview.credentials_key_configured ? <StatusBanner tone="error" message={t("banner.noCredentialsKey")} /> : null}
      {overview.write_fenced ? <StatusBanner tone="error" message={t("banner.fenced")} /> : null}

      <article className="card">
        <DataToolbar title={t("active.title")} />
        <dl className="storage-facts">
          <dt>{t("active.profile")}</dt>
          <dd><strong>{active.name}</strong> <span className="muted">({t(`provider.${active.provider}`)})</span></dd>
          <dt>{t("active.generation")}</dt>
          <dd>g{overview.active_generation}</dd>
          <dt>{t("active.location")}</dt>
          <dd>{active.provider === "filesystem" ? t("active.filesystem") : `${active.endpoint_url ?? "AWS"} · ${active.bucket ?? ""}${active.prefix ? `/${active.prefix}` : ""}`}</dd>
          <dt>{t("active.localS3")}</dt>
          <dd>
            {overview.local_s3.configured ? (
              <>
                <Badge variant={overview.local_s3.needed ? "success" : "neutral"}>{overview.local_s3.needed ? t("localS3.needed") : t("localS3.notNeeded")}</Badge>{" "}
                <span className="muted">{t(`localS3.reason.${overview.local_s3.reason}`)}</span>{" "}
                {!overview.local_s3.needed ? (
                  <button type="button" className="button-secondary button-ghost" disabled={busy !== null}
                    onClick={() => void run("local", () => browserApiFetch("/api/admin/storage/local-s3/request", { method: "POST" }), t("toast.localRequested"))}>
                    {t("actions.requestLocal")}
                  </button>
                ) : null}
              </>
            ) : <span className="muted">{t("localS3.notConfigured")}</span>}
          </dd>
        </dl>
      </article>

      {overview.open_migration ? <MigrationPanel migration={overview.open_migration} t={t} locale={locale} busy={busy} run={run} /> : null}

      <article className="card">
        <DataToolbar title={t("profiles.title")} description={t("profiles.description")} />
        <DataTable columns={[t("columns.name"), t("columns.location"), t("columns.status"), t("columns.lastTest"), t("columns.actions")]} emptyMessage={t("profiles.empty")}>
          {overview.profiles.map((profile) => (
            <tr key={profile.id}>
              <td><strong>{profile.name}</strong><div className="muted">{t(`provider.${profile.provider}`)}</div></td>
              <td className="muted">{profile.provider === "filesystem" ? t("active.filesystem") : `${profile.endpoint_url ?? "AWS"} · ${profile.bucket ?? ""}${profile.prefix ? `/${profile.prefix}` : ""}`}</td>
              <td>
                <div className="storage-badges">
                  {profile.is_active ? <Badge variant="success">{t("status.active")}</Badge> : null}
                  {profile.is_builtin ? <Badge variant="neutral">{t("status.builtin")}</Badge> : null}
                  {!profile.is_enabled ? <Badge variant="neutral">{t("status.disabled")}</Badge> : null}
                  {profile.in_use_by_migration ? <Badge variant="info">{t("status.inMigration")}</Badge> : null}
                  {profile.pinned_generations.length && !profile.is_active ? <Badge variant="warning">{t("status.pinned")}</Badge> : null}
                  {profile.provider !== "filesystem" && !profile.has_restricted_credentials ? <Badge variant="warning">{t("status.sharedCredentials")}</Badge> : null}
                </div>
              </td>
              <td>
                {profile.provider === "filesystem" ? "—" : profile.last_test_at ? (
                  <><Badge variant={profile.last_test_ok ? "success" : "danger"}>{profile.last_test_ok ? t("test.ok") : t("test.failed")}</Badge>{" "}
                    <span className="muted">{formatDateTime(profile.last_test_at, locale)}</span></>
                ) : <span className="muted">{t("test.never")}</span>}
              </td>
              <td>
                {profile.provider === "filesystem" ? null : (
                  <ActionMenu items={[
                    { label: t("actions.test"), onClick: () => void testProfile(profile) },
                    { label: t("actions.edit"), onClick: () => setEditing(profile) },
                    { label: t("actions.delete"), onClick: () => void deleteProfile(profile), danger: true },
                  ]} />
                )}
              </td>
            </tr>
          ))}
        </DataTable>
      </article>

      <article className="card">
        <DataToolbar title={t("generations.title")} description={t("generations.description")} />
        <DataTable columns={[t("columns.generation"), t("columns.profile"), t("columns.status"), t("columns.size"), t("columns.retainUntil"), t("columns.actions")]} emptyMessage={t("generations.empty")}>
          {overview.generations.map((generation) => (
            <tr key={generation.id}>
              <td>g{generation.generation}</td>
              <td>{generation.profile_name}</td>
              <td><Badge variant={GENERATION_VARIANTS[generation.status]}>{t(`generationStatus.${generation.status}`)}</Badge>{generation.purge_error ? <div className="muted">{generation.purge_error}</div> : null}</td>
              <td>{generation.object_count !== null ? t("generations.size", { count: generation.object_count, size: formatFileSize(generation.total_bytes ?? 0) }) : "—"}</td>
              <td>{generation.retain_until ? formatDateTime(generation.retain_until, locale) : "—"}</td>
              <td>
                {generation.status === "retained" || generation.status === "abandoned" ? (
                  <button type="button" className="button-danger" onClick={() => setPurging(generation)}>{t("actions.purge")}</button>
                ) : null}
              </td>
            </tr>
          ))}
        </DataTable>
      </article>

      <article className="card">
        <DataToolbar title={t("history.title")} />
        <DataTable columns={[t("columns.created"), t("columns.route"), t("columns.status"), t("columns.objects"), t("columns.actions")]} emptyMessage={t("history.empty")}>
          {history.map((migration) => (
            <tr key={migration.id}>
              <td>{formatDateTime(migration.created_at, locale)}</td>
              <td>{migration.source_profile_name} → {migration.target_profile_name}</td>
              <td><Badge variant={MIGRATION_VARIANTS[migration.state]}>{t(`state.${migration.state}`)}</Badge></td>
              <td>{t("history.objects", { verified: migration.verified_objects, total: migration.total_objects })}</td>
              <td><a className="button-secondary button-ghost" href={`/api/admin/storage/migrations/${migration.id}/report`}>{t("actions.report")}</a></td>
            </tr>
          ))}
        </DataTable>
      </article>

      {editing ? <ProfileModal t={t} profile={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); void reload(); }} /> : null}
      {starting ? <StartMigrationModal t={t} overview={overview} onClose={() => setStarting(false)} onSaved={() => { setStarting(false); void reload(); }} /> : null}
      {purging ? <PurgeModal t={t} generation={purging} onClose={() => setPurging(null)} onSaved={() => { setPurging(null); void reload(); }} /> : null}
    </div>
  );
}

function MigrationPanel({ migration, t, locale, busy, run }: {
  migration: StorageMigration; t: TFunc; locale: string; busy: string | null;
  run: (key: string, request: () => Promise<unknown>, success: string) => Promise<void>;
}) {
  const confirm = useConfirm();
  const heartbeatAge = secondsSince(migration.heartbeat_at);
  const runtime = secondsSince(migration.started_at);
  const dead = migration.status_counts.dead?.objects ?? 0;
  const base = `/api/admin/storage/migrations/${migration.id}`;
  const terminal = ["completed", "failed", "cancelled"].includes(migration.state);
  const canInterrupt = !["cutting_over", "observing", "rollback_required", ...(terminal ? [migration.state] : [])].includes(migration.state);

  async function action(name: string, path: string, message: string, tone: "default" | "danger" = "default") {
    if (!(await confirm({ message, tone, confirmLabel: t(`actions.${name}`) }))) return;
    await run(`${migration.id}:${name}`, () => browserApiFetch(`${base}/${path}`, { method: "POST" }), t(`toast.${name}`));
  }

  const full = migration.estimate?.full ?? null;
  const cutover = migration.estimate?.cutover ?? null;
  return (
    <article className="card storage-migration" aria-live="polite">
      <DataToolbar
        title={t("migration.title", { source: migration.source_profile_name, target: migration.target_profile_name })}
        description={migration.kind === "initial" ? t("migration.initialHint") : t("migration.liveHint")}
        actions={<Badge variant={MIGRATION_VARIANTS[migration.state]} dot>{t(`state.${migration.state}`)}</Badge>}
      />
      {migration.state === "awaiting_confirmation" ? (
        <StatusBanner tone="neutral" message={migration.kind === "initial"
          ? t("migration.confirmInitial", { range: rangeText(t, full?.remaining_low_seconds, full?.remaining_high_seconds) })
          : t("migration.confirmLive", { range: rangeText(t, full?.remaining_low_seconds, full?.remaining_high_seconds), cutover: rangeText(t, cutover?.remaining_low_seconds, cutover?.remaining_high_seconds) })} />
      ) : null}
      {migration.last_error ? <StatusBanner tone="error" message={migration.last_error} /> : null}
      {heartbeatAge !== null && heartbeatAge > HEARTBEAT_STALE_SECONDS && !terminal && !["awaiting_confirmation", "paused"].includes(migration.state) ? (
        <StatusBanner tone="error" message={t("migration.heartbeatStale")} />
      ) : null}
      <div className="storage-progress-block">
        <span>{t("migration.copyProgress", { copied: formatFileSize(migration.copied_bytes), total: formatFileSize(migration.total_bytes) })}</span>
        <progress className="storage-progress" max={Math.max(migration.total_bytes, 1)} value={migration.copied_bytes} aria-label={t("migration.copyAria")} />
        <span>{t("migration.verifyProgress", { verified: migration.verified_objects, total: migration.total_objects })}</span>
        <progress className="storage-progress" max={Math.max(migration.total_objects, 1)} value={migration.verified_objects} aria-label={t("migration.verifyAria")} />
      </div>
      <dl className="storage-facts">
        <dt>{t("facts.objects")}</dt><dd>{t("facts.objectCounts", { total: migration.total_objects, copied: migration.copied_objects, verified: migration.verified_objects, failed: migration.failed_objects })}</dd>
        <dt>{t("facts.started")}</dt><dd>{migration.started_at ? formatDateTime(migration.started_at, locale) : "—"}</dd>
        <dt>{t("facts.runtime")}</dt><dd>{runtime !== null ? rangeText(t, runtime, runtime) : "—"}</dd>
        <dt>{t("facts.averageRate")}</dt><dd>{migration.average_bps ? t("facts.rate", { value: formatFileSize(migration.average_bps) }) : "—"}</dd>
        <dt>{t("facts.currentRate")}</dt><dd>{migration.current_bps ? t("facts.rate", { value: formatFileSize(migration.current_bps) }) : "—"}</dd>
        <dt>{t("facts.remaining")}</dt><dd>{migration.live_estimate ? rangeText(t, migration.live_estimate.remaining_low_seconds, migration.live_estimate.remaining_high_seconds) : t("estimate.unknown")}</dd>
        <dt>{t("facts.heartbeat")}</dt><dd>{migration.heartbeat_at ? formatDateTime(migration.heartbeat_at, locale) : "—"} {migration.worker_active ? <Badge variant="success">{t("facts.workerActive")}</Badge> : null}</dd>
        <dt>{t("facts.checkpoint")}</dt><dd>{migration.checkpoint_at ? formatDateTime(migration.checkpoint_at, locale) : "—"}</dd>
        <dt>{t("facts.generation")}</dt><dd>g{migration.source_generation} → g{migration.target_generation}</dd>
        {migration.reference_check ? (<><dt>{t("facts.references")}</dt><dd>{t("facts.referenceCounts", { missing: migration.reference_check.missing_count, unreferenced: migration.reference_check.unreferenced_count })}</dd></>) : null}
      </dl>
      {migration.needs_cutover_confirmation ? <StatusBanner tone="neutral" message={migration.reference_check?.missing_count ? t("migration.cutoverWithMissing", { count: migration.reference_check.missing_count }) : t("migration.cutoverReady")} /> : null}
      {migration.state === "rollback_required" ? <StatusBanner tone="error" message={t("migration.rollbackRequired")} /> : null}
      <div className="table-actions">
        {migration.state === "awaiting_confirmation" ? (
          <button type="button" className="button-primary" disabled={busy !== null} onClick={() => void action("start", "start", migration.kind === "initial" ? t("confirm.startInitial") : t("confirm.startLive"))}>{t("actions.start")}</button>
        ) : null}
        {migration.needs_cutover_confirmation ? (
          <button type="button" className="button-primary" disabled={busy !== null} onClick={() => void action("confirmCutover", "confirm-cutover", t("confirm.cutover"))}>{t("actions.confirmCutover")}</button>
        ) : null}
        {canInterrupt && migration.state === "paused" ? (
          <button type="button" className="button-secondary" disabled={busy !== null} onClick={() => void action("resume", "resume", t("confirm.resume"))}>{t("actions.resume")}</button>
        ) : null}
        {canInterrupt && !["paused", "pending", "preflight", "awaiting_confirmation"].includes(migration.state) ? (
          <button type="button" className="button-secondary" disabled={busy !== null} onClick={() => void action("pause", "pause", t("confirm.pause"))}>{t("actions.pause")}</button>
        ) : null}
        {migration.failed_objects > 0 ? (
          <button type="button" className="button-secondary" disabled={busy !== null} onClick={() => void action("retryFailed", "retry-failed", t("confirm.retryFailed"))}>{t("actions.retryFailed")}</button>
        ) : null}
        {dead > 0 ? (
          <button type="button" className="button-secondary" disabled={busy !== null} onClick={() => void action("acceptMissing", "accept-missing", t("confirm.acceptMissing"), "danger")}>{t("actions.acceptMissing")}</button>
        ) : null}
        {migration.state === "rollback_required" ? (
          <button type="button" className="button-secondary" disabled={busy !== null} onClick={() => void action("acknowledgeRollback", "acknowledge-rollback", t("confirm.acknowledgeRollback"))}>{t("actions.acknowledgeRollback")}</button>
        ) : null}
        <a className="button-secondary button-ghost" href={`${base}/report`}>{t("actions.report")}</a>
        {canInterrupt ? (
          <button type="button" className="button-danger" disabled={busy !== null || migration.cancel_requested} onClick={() => void action("cancel", "cancel", t("confirm.cancel"), "danger")}>{t("actions.cancel")}</button>
        ) : null}
      </div>
      <details className="storage-events">
        <summary>{t("events.title", { count: migration.events.length })}</summary>
        <DataTable columns={[t("columns.time"), t("columns.event"), t("columns.actor")]} emptyMessage={t("events.empty")}>
          {migration.events.map((event) => (
            <tr key={event.id}>
              <td>{formatDateTime(event.created_at, locale)}</td>
              <td>
                <Badge variant={event.level === "error" ? "danger" : event.level === "warning" ? "warning" : "neutral"}>{event.to_state ? t(`state.${event.to_state as StorageMigrationState}`) : event.kind}</Badge>{" "}
                {event.message ?? ""}
              </td>
              <td className="muted">{event.actor_email ?? t("events.worker")}</td>
            </tr>
          ))}
        </DataTable>
      </details>
    </article>
  );
}

type ProfileForm = {
  name: string; provider: StorageProvider; endpoint_url: string; region: string; bucket: string; abgabebox_bucket: string; prefix: string;
  addressing_style: "auto" | "path" | "virtual"; access_key: string; secret_key: string; restricted_access_key: string; restricted_secret_key: string;
  tls_verify: boolean; ca_bundle_pem: string; is_enabled: boolean;
};

function ProfileModal({ t, profile, onClose, onSaved }: { t: TFunc; profile: StorageProfile | null; onClose: () => void; onSaved: () => void }) {
  const showToast = useToast();
  const [form, setForm] = useState<ProfileForm>({
    name: profile?.name ?? "", provider: (profile?.provider as StorageProvider) ?? "hetzner", endpoint_url: profile?.endpoint_url ?? "",
    region: profile?.region ?? "", bucket: profile?.bucket ?? "", abgabebox_bucket: profile?.abgabebox_bucket ?? "", prefix: profile?.prefix ?? "",
    addressing_style: profile?.addressing_style ?? "auto", access_key: "", secret_key: "", restricted_access_key: "", restricted_secret_key: "",
    tls_verify: profile?.tls_verify ?? true, ca_bundle_pem: "", is_enabled: profile?.is_enabled ?? true,
  });
  const [saving, setSaving] = useState(false);
  const locked = profile !== null && (profile.is_active || profile.pinned_generations.length > 0 || profile.is_builtin);
  const update = <K extends keyof ProfileForm>(key: K, value: ProfileForm[K]) => setForm((current) => ({ ...current, [key]: value }));
  const valid = form.name.trim() !== "" && form.bucket.trim() !== "" && (profile !== null || (form.access_key !== "" && form.secret_key !== ""));

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    // Leere Zugangsdaten beim Bearbeiten = unverändert lassen (nie an das Backend senden).
    const payload: Record<string, unknown> = { name: form.name, tls_verify: form.tls_verify, is_enabled: form.is_enabled };
    if (!locked) {
      Object.assign(payload, {
        provider: form.provider, endpoint_url: form.endpoint_url || null, region: form.region || null, bucket: form.bucket,
        abgabebox_bucket: form.abgabebox_bucket || null, prefix: form.prefix, addressing_style: form.addressing_style,
      });
    }
    for (const key of ["access_key", "secret_key", "restricted_access_key", "restricted_secret_key", "ca_bundle_pem"] as const) {
      if (form[key] !== "") payload[key] = form[key];
    }
    try {
      await browserApiFetch(profile ? `/api/admin/storage/profiles/${profile.id}` : "/api/admin/storage/profiles", {
        method: profile ? "PATCH" : "POST", body: JSON.stringify(payload),
      });
      showToast(t("toast.profileSaved"), "success");
      onSaved();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open title={profile ? t("profileForm.editTitle") : t("profileForm.newTitle")} onClose={onClose} size="wide">
      <ModalSaveForm className="grid" onSubmit={submit}>
        {locked ? <StatusBanner tone="neutral" message={t("profileForm.locationLocked")} /> : null}
        <div className="two-col">
          <label className="field-stack"><span className="field-label">{t("profileForm.name")}</span>
            <input className="input" value={form.name} maxLength={120} required onChange={(e) => update("name", e.target.value)} /></label>
          <label className="field-stack"><span className="field-label">{t("profileForm.provider")}</span>
            <select className="input" value={form.provider} disabled={locked} onChange={(e) => update("provider", e.target.value as StorageProvider)}>
              {(PROVIDERS.includes(form.provider) ? PROVIDERS : [...PROVIDERS, form.provider]).map((provider) => <option key={provider} value={provider}>{t(`provider.${provider}`)}</option>)}
            </select></label>
        </div>
        <div className="two-col">
          <label className="field-stack"><span className="field-label">{t("profileForm.endpoint")}</span>
            <input className="input" value={form.endpoint_url} disabled={locked} placeholder="https://fsn1.your-objectstorage.com" onChange={(e) => update("endpoint_url", e.target.value)} />
            <span className="field-help">{t("profileForm.endpointHelp")}</span></label>
          <label className="field-stack"><span className="field-label">{t("profileForm.region")}</span>
            <input className="input" value={form.region} disabled={locked} onChange={(e) => update("region", e.target.value)} /></label>
        </div>
        <div className="two-col">
          <label className="field-stack"><span className="field-label">{t("profileForm.bucket")}</span>
            <input className="input" value={form.bucket} disabled={locked} required onChange={(e) => update("bucket", e.target.value)} /></label>
          <label className="field-stack"><span className="field-label">{t("profileForm.abgabeboxBucket")}</span>
            <input className="input" value={form.abgabebox_bucket} disabled={locked} onChange={(e) => update("abgabebox_bucket", e.target.value)} />
            <span className="field-help">{t("profileForm.abgabeboxBucketHelp")}</span></label>
        </div>
        <div className="two-col">
          <label className="field-stack"><span className="field-label">{t("profileForm.prefix")}</span>
            <input className="input" value={form.prefix} disabled={locked} onChange={(e) => update("prefix", e.target.value)} />
            <span className="field-help">{t("profileForm.prefixHelp")}</span></label>
          <label className="field-stack"><span className="field-label">{t("profileForm.addressing")}</span>
            <select className="input" value={form.addressing_style} disabled={locked} onChange={(e) => update("addressing_style", e.target.value as ProfileForm["addressing_style"])}>
              <option value="auto">{t("addressing.auto")}</option><option value="path">{t("addressing.path")}</option><option value="virtual">{t("addressing.virtual")}</option>
            </select></label>
        </div>
        <div className="two-col">
          <label className="field-stack"><span className="field-label">{t("profileForm.accessKey")}</span>
            <input className="input" value={form.access_key} autoComplete="off" placeholder={profile?.access_key_masked ?? ""} onChange={(e) => update("access_key", e.target.value)} /></label>
          <label className="field-stack"><span className="field-label">{t("profileForm.secretKey")}</span>
            <input className="input" type="password" value={form.secret_key} autoComplete="new-password" placeholder={profile?.has_secret_key ? "••••••••" : ""} onChange={(e) => update("secret_key", e.target.value)} />
            {profile ? <span className="field-help">{t("profileForm.keepSecret")}</span> : null}</label>
        </div>
        <div className="two-col">
          <label className="field-stack"><span className="field-label">{t("profileForm.restrictedAccessKey")}</span>
            <input className="input" value={form.restricted_access_key} autoComplete="off" onChange={(e) => update("restricted_access_key", e.target.value)} /></label>
          <label className="field-stack"><span className="field-label">{t("profileForm.restrictedSecretKey")}</span>
            <input className="input" type="password" value={form.restricted_secret_key} autoComplete="new-password" onChange={(e) => update("restricted_secret_key", e.target.value)} /></label>
        </div>
        <span className="field-help">{t("profileForm.restrictedHelp")}</span>
        <label className="checkbox-row"><input type="checkbox" checked={form.tls_verify} onChange={(e) => update("tls_verify", e.target.checked)} /><span>{t("profileForm.tlsVerify")}</span></label>
        <label className="field-stack"><span className="field-label">{t("profileForm.caBundle")}</span>
          <textarea className="input" rows={3} value={form.ca_bundle_pem} placeholder={profile?.has_ca_bundle ? t("profileForm.caBundleStored") : "-----BEGIN CERTIFICATE-----"} onChange={(e) => update("ca_bundle_pem", e.target.value)} /></label>
        <label className="checkbox-row"><input type="checkbox" checked={form.is_enabled} onChange={(e) => update("is_enabled", e.target.checked)} /><span>{t("profileForm.enabled")}</span></label>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{t("actions.close")}</button>
          <button type="submit" className="button-primary" disabled={!valid || saving}>{t("actions.save")}</button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}

function StartMigrationModal({ t, overview, onClose, onSaved }: { t: TFunc; overview: StorageOverview; onClose: () => void; onSaved: () => void }) {
  const showToast = useToast();
  const candidates = overview.profiles.filter((p) => p.provider !== "filesystem" && !p.is_active && p.is_enabled);
  const [target, setTarget] = useState(candidates[0]?.id ?? "");
  const [parallelism, setParallelism] = useState(4);
  const [bandwidth, setBandwidth] = useState(0);
  const [verifyMode, setVerifyMode] = useState<"full" | "head">("full");
  const [autoCutover, setAutoCutover] = useState(false);
  const [saving, setSaving] = useState(false);
  const initial = overview.active_profile.provider === "filesystem";
  const selected = candidates.find((p) => p.id === target);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      const options: Record<string, unknown> = { parallelism, bandwidth_limit_mbps: bandwidth, verify_mode: verifyMode };
      if (!initial) options.auto_cutover = autoCutover;
      await browserApiFetch("/api/admin/storage/migrations", { method: "POST", body: JSON.stringify({ target_profile_id: target, options }) });
      showToast(t("toast.migrationCreated"), "success");
      onSaved();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open title={t("startForm.title")} onClose={onClose}>
      <ModalSaveForm className="grid" onSubmit={submit}>
        <StatusBanner tone="neutral" message={initial ? t("startForm.initialHint") : t("startForm.liveHint")} />
        <label className="field-stack"><span className="field-label">{t("startForm.target")}</span>
          <select className="input" value={target} onChange={(e) => setTarget(e.target.value)}>
            {candidates.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          {selected && !selected.last_test_ok ? <span className="field-help">{t("startForm.needsTest")}</span> : null}</label>
        <div className="two-col">
          <label className="field-stack"><span className="field-label">{t("startForm.parallelism")}</span>
            <input className="input" type="number" min={1} max={16} value={parallelism} onChange={(e) => setParallelism(Number(e.target.value))} /></label>
          <label className="field-stack"><span className="field-label">{t("startForm.bandwidth")}</span>
            <input className="input" type="number" min={0} value={bandwidth} onChange={(e) => setBandwidth(Number(e.target.value))} />
            <span className="field-help">{t("startForm.bandwidthHelp")}</span></label>
        </div>
        <label className="field-stack"><span className="field-label">{t("startForm.verifyMode")}</span>
          <select className="input" value={verifyMode} onChange={(e) => setVerifyMode(e.target.value as "full" | "head")}>
            <option value="full">{t("verifyMode.full")}</option><option value="head">{t("verifyMode.head")}</option>
          </select></label>
        {!initial ? (
          <label className="checkbox-row"><input type="checkbox" checked={autoCutover} onChange={(e) => setAutoCutover(e.target.checked)} /><span>{t("startForm.autoCutover")}</span></label>
        ) : null}
        <p className="muted">{t("startForm.nextStep")}</p>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{t("actions.close")}</button>
          <button type="submit" className="button-primary" disabled={!target || saving || !selected?.last_test_ok}>{t("actions.prepareMigration")}</button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}

function PurgeModal({ t, generation, onClose, onSaved }: { t: TFunc; generation: StorageGeneration; onClose: () => void; onSaved: () => void }) {
  const showToast = useToast();
  const [confirmation, setConfirmation] = useState("");
  const [saving, setSaving] = useState(false);
  const expected = `g${generation.generation}`;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      await browserApiFetch(`/api/admin/storage/generations/${generation.id}/purge`, { method: "POST", body: JSON.stringify({ confirmation }) });
      showToast(t("toast.purgeRequested"), "success");
      onSaved();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open title={t("purge.title", { generation: expected })} onClose={onClose}>
      <ModalSaveForm className="grid" onSubmit={submit}>
        <StatusBanner tone="error" message={t("purge.warning", { profile: generation.profile_name })} />
        <label className="field-stack"><span className="field-label">{t("purge.label", { expected })}</span>
          <input className="input" value={confirmation} autoComplete="off" onChange={(e) => setConfirmation(e.target.value)} /></label>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{t("actions.close")}</button>
          <button type="submit" className="button-danger" disabled={confirmation !== expected || saving}>{t("actions.purge")}</button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}
