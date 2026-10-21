"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ActionMenu, ActionMenuItem } from "@/components/ui/action-menu";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate, formatDateTime, formatFileSize } from "@/lib/utils/format";
import {
  StorageConnectionTest,
  StorageGeneration,
  StorageMigration,
  StorageMigrationState,
  StorageOverview,
  StorageDataLocation,
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
const DATA_LOCATIONS: StorageDataLocation[] = ["ch", "eu_eea", "adequate", "third_country"];
const LOCATION_VARIANTS: Record<StorageDataLocation, BadgeVariant> = { ch: "success", eu_eea: "success", adequate: "info", third_country: "warning" };

// Gleiche Ableitung wie storage_profile_service.derive_location (Datenschutz-Audit E3); null = Admin wählt.
function derivedLocation(provider: StorageProvider, region: string): StorageDataLocation | null {
  const value = region.trim().toLowerCase();
  if (provider === "aws_s3") return value === "eu-central-2" ? "ch" : value.startsWith("eu-") ? "eu_eea" : "third_country";
  if (provider === "hetzner") return !value || ["fsn1", "nbg1", "hel1"].includes(value) ? "eu_eea" : "third_country";
  return null;
}

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
  const migration = overview.open_migration;
  const activeGeneration = overview.generations.find((generation) => generation.status === "active" && generation.generation === overview.active_generation) ?? null;
  const initialPending = active.provider === "filesystem" && migration === null;
  // Ziel der Erstmigration: bevorzugt das eingebaute lokale S3, sonst das erste aktivierte S3-Profil.
  const initialTarget =
    overview.profiles.find((profile) => profile.provider === "garage_local" && profile.is_enabled) ??
    overview.profiles.find((profile) => profile.provider !== "filesystem" && profile.is_enabled) ??
    null;
  const lastCompleted = history.find((entry) => entry.state === "completed") ?? null;
  const retained = overview.generations.find((generation) => generation.status === "retained" && generation.retain_until) ?? null;
  const step = migrationStep(migration, initialPending, Boolean(initialTarget?.last_test_ok));

  return (
    <div className="grid storage-page">
      <div className="page-header storage-page-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("description")}</p>
        </div>
        <div className="storage-header-actions">
          <button type="button" className="button-secondary" onClick={() => setEditing("new")}>{t("actions.newProfile")}</button>
          <button type="button" className="button-primary" disabled={migration !== null} onClick={() => setStarting(true)}>
            {t("actions.startMigration")}
          </button>
        </div>
      </div>

      {!overview.credentials_key_configured ? <StatusBanner tone="error" message={t("banner.noCredentialsKey")} /> : null}
      {overview.write_fenced ? <StatusBanner tone="error" message={t("banner.fenced")} /> : null}

      <section className="storage-hero" aria-label={t("active.title")}>
        <div className="storage-hero-grid">
          <div className="storage-hero-active">
            <span className="storage-eyebrow"><span className="storage-dot" aria-hidden="true" />{t("active.title")}</span>
            <div className="storage-hero-profile">
              <ProviderIcon provider={active.provider} large />
              <div>
                <div className="storage-hero-name">{active.name}</div>
                <div className="muted">{t(`provider.${active.provider}`)}</div>
              </div>
            </div>
            <dl className="storage-facts">
              <dt>{t("active.generation")}</dt>
              <dd><span className="storage-gen-chip">g{overview.active_generation}</span></dd>
              <dt>{t("active.location")}</dt>
              <dd className="storage-mono">{profileLocation(active, t)}</dd>
              <dt>{t("active.extent")}</dt>
              <dd>{activeGeneration?.object_count !== null && activeGeneration?.object_count !== undefined ? t("generations.size", { count: activeGeneration.object_count, size: formatFileSize(activeGeneration.total_bytes ?? 0) }) : "—"}</dd>
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
          </div>

          <div className="storage-hero-state">
            {migration ? (
              <>
                <Badge variant={MIGRATION_VARIANTS[migration.state]} dot>{t(`state.${migration.state}`)}</Badge>
                <div className="storage-hero-title"><span className="storage-mono">g{migration.source_generation} → g{migration.target_generation}</span> · {migration.target_profile_name}</div>
                <div className="storage-hero-progress">
                  <span className="storage-bar" aria-hidden="true"><span style={{ width: `${percent(migration.copied_objects, migration.total_objects)}%` }} /></span>
                  <div className="storage-hero-progress-text">
                    <span>{t("hero.progress", { copied: migration.copied_objects, total: migration.total_objects })}</span>
                    <span>{percent(migration.copied_objects, migration.total_objects)} %</span>
                  </div>
                </div>
                <p className="muted">{migration.kind === "initial" ? t("migration.initialHint") : t("migration.liveHint")}</p>
              </>
            ) : initialPending ? (
              <>
                <Badge variant="warning">{t("hero.initialPending")}</Badge>
                <div className="storage-hero-title">{initialTarget ? t("hero.target", { name: initialTarget.name }) : t("hero.noTarget")}</div>
                <p className="muted">
                  {initialTarget ? t("hero.initialText", { name: initialTarget.name }) : t("hero.noTargetText")}{" "}
                  {initialTarget ? t(`hero.tested.${initialTarget.last_test_at === null ? "never" : initialTarget.last_test_ok ? "ok" : "failed"}`) : null}
                </p>
                <div className="storage-hero-actions">
                  {initialTarget ? (
                    <button type="button" className="button-secondary" disabled={busy !== null} onClick={() => void testProfile(initialTarget)}>
                      {busy === `test:${initialTarget.id}` ? t("profileCard.testing") : initialTarget.last_test_at ? t("profileCard.retest") : t("actions.test")}
                    </button>
                  ) : (
                    <button type="button" className="button-secondary" onClick={() => setEditing("new")}>{t("actions.newProfile")}</button>
                  )}
                  <button type="button" className="button-primary" disabled={!initialTarget} onClick={() => setStarting(true)}>{t("actions.startMigration")}</button>
                </div>
              </>
            ) : lastCompleted ? (
              <>
                <Badge variant="success">{t("hero.switched", { date: formatDate(lastCompleted.finished_at ?? lastCompleted.created_at) })}</Badge>
                <div className="storage-hero-title">{t("hero.switchedObjects", { count: lastCompleted.verified_objects })}</div>
                {retained ? (
                  <p className="muted">{t("hero.retained", { generation: `g${retained.generation}`, date: formatDate(retained.retain_until) })}</p>
                ) : null}
              </>
            ) : (
              <p className="muted">{t("hero.noMigration")}</p>
            )}
          </div>
        </div>

        <ol className="storage-steps">
          {STEP_KEYS.map((key, index) => {
            const stepState = index < step ? "done" : index === step ? "current" : "next";
            return (
              <li key={key} className={`storage-step storage-step-${stepState}`}>
                <span className="storage-step-mark" aria-hidden="true">{stepState === "done" ? "✓" : index + 1}</span>{/* i18n-ok: Symbol/Nummer */}
                <div>
                  <span className="storage-step-title">{t(`steps.${key}.title`)}</span>
                  <span className="storage-step-description">{t(`steps.${key}.description`)}</span>
                </div>
              </li>
            );
          })}
        </ol>
      </section>

      {migration ? <MigrationPanel migration={migration} t={t} locale={locale} busy={busy} run={run} /> : null}

      <section className="storage-section">
        <div className="storage-section-head">
          <h2 className="storage-section-title">{t("profiles.title")}</h2>
          <span className="muted storage-lock-note">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M6 10.5h12v10H6zM8.5 10.5V7.5a3.5 3.5 0 017 0v3" /></svg>
            {t("profiles.description")}
          </span>
        </div>
        {overview.profiles.length === 0 ? <p className="muted">{t("profiles.empty")}</p> : (
          <div className="storage-profiles">
            {overview.profiles.map((profile) => (
              <ProfileCard
                key={profile.id}
                profile={profile}
                t={t}
                locale={locale}
                busy={busy}
                migrationTarget={migration?.target_profile_name === profile.name}
                onTest={() => void testProfile(profile)}
                onEdit={() => setEditing(profile)}
                onDelete={() => void deleteProfile(profile)}
              />
            ))}
          </div>
        )}
      </section>

      <div className="storage-columns">
        <section className="card storage-list-card">
          <div>
            <h2 className="storage-section-title">{t("generations.title")}</h2>
            <p className="muted storage-small">{t("generations.description")}</p>
          </div>
          {overview.generations.length === 0 && !initialPending ? <p className="muted">{t("generations.empty")}</p> : null}
          <ul className="storage-list">
            {overview.generations.map((generation) => (
              <li key={generation.id}>
                <span className="storage-gen-chip">g{generation.generation}</span>
                <div className="storage-list-text">
                  <div className="storage-list-line">
                    <strong>{generation.profile_name}</strong>
                    <Badge variant={GENERATION_VARIANTS[generation.status]}>{t(`generationStatus.${generation.status}`)}</Badge>
                  </div>
                  <span className="muted storage-small">
                    {[
                      generation.object_count !== null ? t("generations.size", { count: generation.object_count, size: formatFileSize(generation.total_bytes ?? 0) }) : null,
                      generation.status === "active" && generation.activated_at ? t("generations.since", { date: formatDate(generation.activated_at) }) : null,
                      generation.retain_until && generation.status === "retained" ? t("generations.retainUntil", { date: formatDate(generation.retain_until) }) : null,
                    ].filter(Boolean).join(" · ")}
                  </span>
                  {generation.purge_error ? <span className="storage-small storage-error">{generation.purge_error}</span> : null}
                </div>
                {generation.status === "retained" || generation.status === "abandoned" ? (
                  <button type="button" className="button-danger storage-list-action" onClick={() => setPurging(generation)}>{t("actions.purge")}</button>
                ) : null}
              </li>
            ))}
            {initialPending ? (
              <li className="storage-list-ghost">
                <span className="storage-gen-chip">g{overview.active_generation + 1}</span>
                <div className="storage-list-text">
                  <strong>{t("generations.next")}</strong>
                  <span className="muted storage-small">{t("generations.nextMeta")}</span>
                </div>
              </li>
            ) : null}
          </ul>
        </section>

        <section className="card storage-list-card">
          <h2 className="storage-section-title">{t("history.title")}</h2>
          {history.length === 0 ? (
            <div className="storage-empty">
              <strong>{t("history.empty")}</strong>
              <span className="muted storage-small">{t("history.emptyHint")}</span>
            </div>
          ) : (
            <ul className="storage-list storage-migrations">
              {history.map((entry) => (
                <li key={entry.id}>
                  <div className="storage-list-text">
                    <div className="storage-list-line storage-list-line-spread">
                      <strong><span className="storage-mono">g{entry.source_generation} → g{entry.target_generation}</span> · {entry.target_profile_name}</strong>
                      <Badge variant={MIGRATION_VARIANTS[entry.state]}>{t(`state.${entry.state}`)}</Badge>
                    </div>
                    <span className="muted storage-small storage-list-meta">
                      <span>{t("history.created", { date: formatDateTime(entry.created_at, locale) })}</span>
                      <span>{t("history.copied", { copied: entry.copied_objects, total: entry.total_objects })}</span>
                      <span>{t("history.checked", { verified: entry.verified_objects, failed: entry.failed_objects })}</span>
                      <a href={`/api/admin/storage/migrations/${entry.id}/report`}>{t("actions.report")}</a>
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {editing ? <ProfileModal t={t} profile={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); void reload(); }} /> : null}
      {starting ? (
        <StartMigrationModal t={t} overview={overview} activeGeneration={activeGeneration} busy={busy} onTest={(profile) => void testProfile(profile)}
          onClose={() => setStarting(false)} onSaved={() => { setStarting(false); void reload(); }} />
      ) : null}
      {purging ? <PurgeModal t={t} generation={purging} onClose={() => setPurging(null)} onSaved={() => { setPurging(null); void reload(); }} /> : null}
    </div>
  );
}

const STEP_KEYS = ["prepare", "copy", "verify", "switch"] as const;

/** Index des aktuellen Schritts (0-3), 4 = alles erledigt. */
export function migrationStep(migration: StorageMigration | null, initialPending: boolean, targetTested: boolean): number {
  if (!migration) return initialPending ? (targetTested ? 1 : 0) : 4;
  const state = ["paused", "retrying"].includes(migration.state) ? migration.resume_state ?? "copying" : migration.state;
  if (["pending", "preflight", "awaiting_confirmation"].includes(state)) return 0;
  if (["inventory", "copying", "catching_up"].includes(state)) return 1;
  if (state === "verifying") return 2;
  if (["ready_for_cutover", "cutting_over", "rollback_required"].includes(state)) return 3;
  if (["observing", "completed"].includes(state)) return 4;
  return 1;
}

function percent(value: number, total: number): number {
  return total > 0 ? Math.min(100, Math.round((value / total) * 100)) : 0;
}

function profileLocation(profile: StorageProfile, t: TFunc): string {
  if (profile.provider === "filesystem") return t("active.filesystem");
  return `${profile.endpoint_url ?? "AWS"} · ${profile.bucket ?? ""}${profile.prefix ? `/${profile.prefix}` : ""}`; // i18n-ok: technische Adresse
}

function ProviderIcon({ provider, large = false }: { provider: StorageProvider; large?: boolean }) {
  const path = provider === "filesystem"
    ? "M3.5 7a1.5 1.5 0 011.5-1.5h4.5l2 2.5H19a1.5 1.5 0 011.5 1.5v8A1.5 1.5 0 0119 19H5a1.5 1.5 0 01-1.5-1.5z"
    : "M4 6.5h16l-1.6 12.2a1.5 1.5 0 01-1.5 1.3H7.1a1.5 1.5 0 01-1.5-1.3zM3.5 6.5c0-1.7 3.8-3 8.5-3s8.5 1.3 8.5 3";
  return (
    <span className={`storage-provider-icon${large ? " storage-provider-icon-large" : ""}`} aria-hidden="true">
      <svg width={large ? 22 : 19} height={large ? 22 : 19} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d={path} /></svg>
    </span>
  );
}

function ProfileCard({ profile, t, locale, busy, migrationTarget, onTest, onEdit, onDelete }: {
  profile: StorageProfile; t: TFunc; locale: string; busy: string | null; migrationTarget: boolean; onTest: () => void; onEdit: () => void; onDelete: () => void;
}) {
  const filesystem = profile.provider === "filesystem";
  const testing = busy === `test:${profile.id}`;
  const testTone = filesystem ? "neutral" : testing ? "running" : profile.last_test_at === null ? "never" : profile.last_test_ok ? "ok" : "failed";
  const testText = filesystem
    ? t("profileCard.noTestNeeded")
    : testing
      ? t("profileCard.testing")
      : profile.last_test_at === null
        ? t("test.never")
        : t(profile.last_test_ok ? "profileCard.lastTestOk" : "profileCard.lastTestFailed", { time: formatDateTime(profile.last_test_at, locale) });
  const menu: ActionMenuItem[] = [{ label: t("actions.edit"), onClick: onEdit }];
  if (!profile.is_builtin && !profile.is_active) menu.push({ label: t("actions.delete"), onClick: onDelete, danger: true });
  return (
    <article className={`storage-profile${profile.is_active ? " storage-profile-active" : ""}`}>
      <div className="storage-profile-head">
        <ProviderIcon provider={profile.provider} />
        <div className="storage-profile-name">
          <strong>{profile.name}</strong>
          <span className="muted storage-small">{t(`provider.${profile.provider}`)}</span>
          <div className="storage-badges">
            {profile.is_active ? <Badge variant="success">{t("status.active")}</Badge> : null}
            {migrationTarget || profile.in_use_by_migration ? <Badge variant="info">{t("status.inMigration")}</Badge> : null}
            {profile.is_builtin ? <Badge variant="neutral">{t("status.builtin")}</Badge> : null}
            {!profile.is_enabled ? <Badge variant="neutral">{t("status.disabled")}</Badge> : null}
            {profile.pinned_generations.length && !profile.is_active ? <Badge variant="warning">{t("status.pinned")}</Badge> : null}
            {!filesystem && !profile.has_restricted_credentials ? <Badge variant="warning">{t("status.sharedCredentials")}</Badge> : null}
            {profile.data_location ? <Badge variant={LOCATION_VARIANTS[profile.data_location]}>{t(`location.${profile.data_location}`)}</Badge> : null}
            {profile.server_side_encryption ? <Badge variant="neutral">{t("status.encrypted")}</Badge> : null}
          </div>
        </div>
      </div>
      <dl className="storage-facts storage-profile-facts">
        {filesystem ? (
          <><dt>{t("active.location")}</dt><dd>{t("active.filesystem")}</dd></>
        ) : (
          <>
            <dt>{t("profileCard.endpoint")}</dt><dd className="storage-mono">{profile.endpoint_url ?? "AWS"}</dd>{/* i18n-ok: Anbietername */}
            <dt>{t("profileCard.bucket")}</dt><dd className="storage-mono">{profile.bucket ?? "—"}{profile.prefix ? ` / ${profile.prefix}` : ""}</dd>
            {profile.abgabebox_bucket ? <><dt>{t("profileCard.abgabeboxBucket")}</dt><dd className="storage-mono">{profile.abgabebox_bucket}</dd></> : null}
            <dt>{t("profileCard.credentials")}</dt>
            <dd>{profile.has_secret_key ? t("profileCard.credentialsStored") : t("profileCard.credentialsMissing")}</dd>
          </>
        )}
      </dl>
      {!filesystem && profile.last_test_ok === false && profile.last_test_error ? <span className="storage-small storage-error">{profile.last_test_error}</span> : null}
      <div className="storage-profile-foot">
        <span className={`storage-test-dot storage-test-${testTone}`} aria-hidden="true" />
        <span className="storage-profile-test">{testText}</span>
        {!filesystem ? (
          <button type="button" className="button-secondary storage-small-button" disabled={busy !== null} onClick={onTest}>
            {profile.last_test_at ? t("profileCard.retest") : t("actions.test")}
          </button>
        ) : null}
        {!filesystem ? <ActionMenu items={menu} /> : null}
      </div>
    </article>
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
  data_location: StorageDataLocation | ""; transfer_basis: string; location_confirmed: boolean; server_side_encryption: boolean;
};

function ProfileModal({ t, profile, onClose, onSaved }: { t: TFunc; profile: StorageProfile | null; onClose: () => void; onSaved: () => void }) {
  const showToast = useToast();
  const [form, setForm] = useState<ProfileForm>({
    name: profile?.name ?? "", provider: (profile?.provider as StorageProvider) ?? "hetzner", endpoint_url: profile?.endpoint_url ?? "",
    region: profile?.region ?? "", bucket: profile?.bucket ?? "", abgabebox_bucket: profile?.abgabebox_bucket ?? "", prefix: profile?.prefix ?? "",
    addressing_style: profile?.addressing_style ?? "auto", access_key: "", secret_key: "", restricted_access_key: "", restricted_secret_key: "",
    tls_verify: profile?.tls_verify ?? true, ca_bundle_pem: "", is_enabled: profile?.is_enabled ?? true,
    data_location: profile?.data_location ?? "", transfer_basis: profile?.transfer_basis ?? "", location_confirmed: false,
    server_side_encryption: profile?.server_side_encryption ?? false,
  });
  const [saving, setSaving] = useState(false);
  const locked = profile !== null && (profile.is_active || profile.pinned_generations.length > 0 || profile.is_builtin);
  const update = <K extends keyof ProfileForm>(key: K, value: ProfileForm[K]) => setForm((current) => ({ ...current, [key]: value }));
  const location = derivedLocation(form.provider, form.region) ?? (form.data_location || null);
  const thirdCountry = location === "third_country";
  const needsConfirmation = thirdCountry && profile?.data_location !== "third_country";
  const valid = form.name.trim() !== "" && form.bucket.trim() !== "" && (profile !== null || (form.access_key !== "" && form.secret_key !== ""))
    && location !== null && (!thirdCountry || (form.transfer_basis.trim() !== "" && (!needsConfirmation || form.location_confirmed)));

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    // Leere Zugangsdaten beim Bearbeiten = unverändert lassen (nie an das Backend senden).
    const payload: Record<string, unknown> = {
      name: form.name, tls_verify: form.tls_verify, is_enabled: form.is_enabled, server_side_encryption: form.server_side_encryption,
      transfer_basis: form.transfer_basis, location_confirmed: form.location_confirmed,
    };
    if (form.provider === "s3_compatible" && form.data_location) payload.data_location = form.data_location;
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
        <label className="checkbox-row"><input type="checkbox" checked={form.server_side_encryption} onChange={(e) => update("server_side_encryption", e.target.checked)} /><span>{t("profileForm.serverSideEncryption")}</span></label>
        <span className="field-help">{t("profileForm.serverSideEncryptionHelp")}</span>
        {/* Datenstandort (Datenschutz-Audit E3): bei AWS/Hetzner aus der Region abgeleitet */}
        <label className="field-stack"><span className="field-label">{t("profileForm.dataLocation")}</span>
          {form.provider === "s3_compatible" ? (
            <select className="input" value={form.data_location} onChange={(e) => update("data_location", e.target.value as ProfileForm["data_location"])}>
              <option value="">{t("profileForm.dataLocationChoose")}</option>
              {DATA_LOCATIONS.map((value) => <option key={value} value={value}>{t(`location.${value}`)}</option>)}
            </select>
          ) : (
            <input className="input" value={location ? t(`location.${location}`) : ""} readOnly />
          )}
          <span className="field-help">{t("profileForm.dataLocationHelp")}</span></label>
        {thirdCountry ? (
          <>
            <label className="field-stack"><span className="field-label">{t("profileForm.transferBasis")}</span>
              <textarea className="input" rows={2} maxLength={1000} value={form.transfer_basis} onChange={(e) => update("transfer_basis", e.target.value)} />
              <span className="field-help">{t("profileForm.transferBasisHelp")}</span></label>
            {needsConfirmation ? (
              <label className="checkbox-row"><input type="checkbox" checked={form.location_confirmed} onChange={(e) => update("location_confirmed", e.target.checked)} /><span>{t("profileForm.locationConfirm")}</span></label>
            ) : null}
          </>
        ) : null}
        <label className="checkbox-row"><input type="checkbox" checked={form.is_enabled} onChange={(e) => update("is_enabled", e.target.checked)} /><span>{t("profileForm.enabled")}</span></label>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{t("actions.close")}</button>
          <button type="submit" className="button-primary" disabled={!valid || saving}>{t("actions.save")}</button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}

function StartMigrationModal({ t, overview, activeGeneration, busy, onTest, onClose, onSaved }: {
  t: TFunc; overview: StorageOverview; activeGeneration: StorageGeneration | null; busy: string | null;
  onTest: (profile: StorageProfile) => void; onClose: () => void; onSaved: () => void;
}) {
  const showToast = useToast();
  const candidates = overview.profiles.filter((p) => p.provider !== "filesystem" && !p.is_active && p.is_enabled);
  const [target, setTarget] = useState(
    (candidates.find((p) => p.provider === "garage_local" && overview.active_profile.provider === "filesystem") ?? candidates[0])?.id ?? "",
  );
  const [parallelism, setParallelism] = useState(4);
  const [bandwidth, setBandwidth] = useState(0);
  const [verifyMode, setVerifyMode] = useState<"full" | "head">("full");
  const [autoCutover, setAutoCutover] = useState(false);
  const [confirmThirdCountry, setConfirmThirdCountry] = useState(false);
  const [saving, setSaving] = useState(false);
  const initial = overview.active_profile.provider === "filesystem";
  const selected = candidates.find((p) => p.id === target);
  const tested = Boolean(selected?.last_test_ok);
  const testState = !selected ? "missing" : tested ? "ok" : selected.last_test_at ? "failed" : "missing";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      const options: Record<string, unknown> = { parallelism, bandwidth_limit_mbps: bandwidth, verify_mode: verifyMode };
      if (!initial) options.auto_cutover = autoCutover;
      await browserApiFetch("/api/admin/storage/migrations", {
        method: "POST", body: JSON.stringify({ target_profile_id: target, options, confirm_third_country: confirmThirdCountry }),
      });
      showToast(t("toast.migrationCreated"), "success");
      onSaved();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open title={t("startForm.title")} onClose={onClose} size="wide">
      <ModalSaveForm className="grid" onSubmit={submit}>
        <p className="muted">{initial ? t("startForm.initialHint") : t("startForm.liveHint")}</p>
        <div className="storage-route">
          <div className="storage-route-card">
            <span className="storage-eyebrow">{t("startForm.from")}</span>
            <strong>{overview.active_profile.name}</strong>
            <span className="muted storage-small">
              <span className="storage-mono">g{overview.active_generation}</span>
              {activeGeneration?.object_count !== null && activeGeneration?.object_count !== undefined
                ? ` · ${t("generations.size", { count: activeGeneration.object_count, size: formatFileSize(activeGeneration.total_bytes ?? 0) })}`
                : null}
            </span>
          </div>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true" className="storage-route-arrow"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
          <div className="storage-route-card storage-route-target">
            <span className="storage-eyebrow">{t("startForm.to")}</span>
            {candidates.length > 1 ? (
              <select className="input" aria-label={t("startForm.target")} value={target} onChange={(e) => setTarget(e.target.value)}>
                {candidates.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            ) : (
              <strong>{selected?.name ?? t("hero.noTarget")}</strong>
            )}
            {selected ? (
              <span className="muted storage-small">
                {t("startForm.newGeneration", { generation: `g${overview.active_generation + 1}` })}
                {selected.bucket ? ` · ${selected.bucket}${selected.prefix ? `/${selected.prefix}` : ""}` : null}
              </span>
            ) : null}
          </div>
        </div>

        <div className={`storage-test-box storage-test-box-${testState}`}>
          <span className={`storage-test-dot storage-test-${testState === "missing" ? "never" : testState}`} aria-hidden="true" />
          <div className="storage-test-box-text">
            <strong>{t(`startForm.test.${testState}.title`)}</strong>
            <span className="muted storage-small">
              {testState === "failed" && selected?.last_test_error ? selected.last_test_error : t(`startForm.test.${testState}.text`)}
            </span>
          </div>
          {selected && !tested ? (
            <button type="button" className="button-secondary storage-small-button" disabled={busy !== null} onClick={() => onTest(selected)}>
              {busy === `test:${selected.id}` ? t("profileCard.testing") : t("actions.test")}
            </button>
          ) : null}
        </div>

        <div className="field-stack">
          <span className="field-label">{t("startForm.flow")}</span>
          <ol className="storage-flow">
            {STEP_KEYS.map((key, index) => (
              <li key={key}>
                <span className="storage-mono storage-flow-number">{String(index + 1).padStart(2, "0")}</span>
                <span><strong>{t(`steps.${key}.title`)}</strong> – {t(`steps.${key}.description`)}</span>
              </li>
            ))}
          </ol>
          <span className="field-help">{t("startForm.retention")}</span>
        </div>

        <details className="storage-advanced">
          <summary>{t("startForm.advanced")}</summary>
          <div className="grid">
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
          </div>
        </details>
        <p className="muted">{t("startForm.nextStep")}</p>
        {selected?.data_location === "third_country" ? (
          <label className="checkbox-row"><input type="checkbox" checked={confirmThirdCountry} onChange={(e) => setConfirmThirdCountry(e.target.checked)} /><span>{t("startForm.confirmThirdCountry")}</span></label>
        ) : null}
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{t("actions.close")}</button>
          <button type="submit" className="button-primary" disabled={!target || saving || !tested || (selected?.data_location === "third_country" && !confirmThirdCountry)}>{t("actions.prepareMigration")}</button>
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
