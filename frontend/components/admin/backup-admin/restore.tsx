"use client";

import { FormEvent, KeyboardEvent, useCallback, useEffect, useState } from "react";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { stepUpFetch } from "@/lib/admin-step-up";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime, formatFileSize } from "@/lib/utils/format";
import type { BackupJob, BackupJobPage, BackupSet, BackupStatus, BackupTenant, RestoreJob, RestorePreview, StorageOverview } from "@/types/api";

import { ageText, errorText, JOB_VARIANTS, RESTORE_VARIANTS, RestorePanel, useIdempotencyKey, type TFunc } from "./shared";

type RestoreKind = "tenant_copy" | "full";
const POINTS_SHOWN = 8;
const TENANT_CARDS_MAX = 6;

function setBadges(t: TFunc, set: BackupSet): Array<{ label: string; variant: BadgeVariant }> {
  const badges: Array<{ label: string; variant: BadgeVariant }> = [];
  if (set.protected) badges.push({ label: t("history.protected"), variant: "info" });
  badges.push(set.state === "partial" ? { label: t("setState.partial"), variant: "warning" } : { label: t("setState.completed"), variant: "success" });
  badges.push(set.verify_state === "verified" ? { label: t("verify.verified"), variant: "success" }
    : set.verify_state === "failed" ? { label: t("verify.failed"), variant: "danger" } : { label: t("verify.unverified"), variant: "neutral" });
  if (set.restore_test_state === "passed") badges.push({ label: t("restoreTest.passed"), variant: "success" });
  return badges;
}

export function Restore({ t, locale, isOwner, status, onChanged }: { t: TFunc; locale: string; isOwner: boolean; status: BackupStatus; onChanged: () => Promise<void> }) {
  const showToast = useToast();
  const confirm = useConfirm();
  const [sets, setSets] = useState<BackupSet[]>([]);
  const [profiles, setProfiles] = useState<StorageOverview["profiles"]>([]);
  const [history, setHistory] = useState<RestoreJob[]>([]);
  const [tests, setTests] = useState<BackupJob[]>([]);
  const [kind, setKind] = useState<RestoreKind>("tenant_copy");
  const [setId, setSetId] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [tenants, setTenants] = useState<BackupTenant[]>([]);
  const [tenantId, setTenantId] = useState<number | null>(null);
  const [newName, setNewName] = useState("");
  const [profileId, setProfileId] = useState<string | null>(null);
  const [preview, setPreview] = useState<RestorePreview | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [skipRescue, setSkipRescue] = useState(false);
  const [skipReason, setSkipReason] = useState("");
  const [replayErasures, setReplayErasures] = useState(true);
  const [replayReason, setReplayReason] = useState("");
  const [working, setWorking] = useState(false);
  const [watching, setWatching] = useState<string | null>(status.current_restore?.id ?? null);
  const [now] = useState(() => Date.now());
  const { get: restoreKeyFor, reset: resetRestoreKey } = useIdempotencyKey();

  const loadHistory = useCallback(async () => {
    try {
      const [restores, testPage] = await Promise.all([
        browserApiFetch<RestoreJob[]>("/api/admin/restores?limit=10"),
        browserApiFetch<BackupJobPage>("/api/admin/backups?kind=restore_test&limit=10"),
      ]);
      setHistory(restores);
      setTests(testPage.items);
    } catch {
      // Verlauf ist optional.
    }
  }, []);

  useEffect(() => {
    if (!isOwner) return;
    void (async () => {
      try {
        setSets(await browserApiFetch<BackupSet[]>("/api/admin/backups/sets"));
        const overview = await browserApiFetch<StorageOverview>("/api/admin/storage/overview");
        setProfiles(overview.profiles.filter((profile) => profile.provider !== "filesystem" && profile.is_enabled));
      } catch {
        // Ohne Liste bleibt der Assistent leer, Fehler zeigt die Vorschau.
      }
    })();
  }, [isOwner]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    setTenantId(null);
    setTenants([]);
    setPreview(null);
    if (!setId) return;
    void browserApiFetch<BackupTenant[]>(`/api/admin/backups/sets/${setId}/tenants`).then(setTenants).catch(() => setTenants([]));
  }, [setId]);

  // Jede Änderung an Art, Punkt, Mandant, Name oder Profil verwirft Vorschau und Phrase.
  useEffect(() => {
    setPreview(null);
    setConfirmation("");
  }, [kind, tenantId, newName, profileId]);

  // Neue Vorschau = neue Bestätigung = neuer Schlüssel.
  useEffect(() => {
    resetRestoreKey();
  }, [preview, resetRestoreKey]);

  async function loadPreview() {
    if (!setId) return;
    setWorking(true);
    try {
      setPreview(await browserApiFetch<RestorePreview>("/api/admin/restores/preview", {
        method: "POST",
        body: JSON.stringify({ backup_set_id: setId, kind, target_profile_id: kind === "full" ? profileId : null,
          source_tenant_id: kind === "tenant_copy" ? tenantId : null, new_name: kind === "tenant_copy" ? newName : null }),
      }));
      setConfirmation("");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setWorking(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!preview || !setId || !canSubmit) return;
    if (kind === "full" && !(await confirm({ message: t("confirm.fullRestore"), tone: "danger", confirmLabel: t("actions.startRestore") }))) return;
    setWorking(true);
    try {
      // Frische Passkey-Bestätigung (Step-up), gebunden an genau diese Anfrage (Security-Review M2/L7).
      const restoreBody = JSON.stringify({
        backup_set_id: setId, kind, target_profile_id: kind === "full" ? profileId : null, source_tenant_id: kind === "tenant_copy" ? tenantId : null,
        new_name: kind === "tenant_copy" ? newName : null, confirmation,
        skip_rescue_backup: kind === "full" ? skipRescue : false, skip_rescue_reason: skipRescue ? skipReason : null,
        replay_erasures: replayErasures, replay_erasures_reason: replayErasures ? null : replayReason,
        idempotency_key: restoreKeyFor(`restore-${setId}`),
      });
      const job = await stepUpFetch<RestoreJob>("backup-restore", "/api/admin/restores", { method: "POST", body: restoreBody });
      showToast(t("toast.restoreQueued"), "success");
      setWatching(job.id);
      setPreview(null);
      setConfirmation("");
      await onChanged();
      await loadHistory();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setWorking(false);
    }
  }

  // Enter im Phrasenfeld löst nie den Start aus - gestartet wird nur über den Knopf.
  function blockEnter(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") event.preventDefault();
  }

  const selectedSet = sets.find((item) => item.id === setId) ?? null;
  const selectedTenant = tenants.find((item) => item.id === tenantId) ?? null;
  const canPreview = setId !== null && (kind === "full" || (tenantId !== null && newName.trim() !== ""));
  const phraseOk = preview !== null && confirmation.trim() === preview.confirmation_phrase;
  const canSubmit = preview !== null && preview.blockers.length === 0 && phraseOk
    && (!skipRescue || skipReason.trim() !== "") && (replayErasures || replayReason.trim() !== "");
  const tenantCards = tenants.length <= TENANT_CARDS_MAX;
  const visibleSets = showAll ? sets : sets.slice(0, POINTS_SHOWN);
  const shownSets = selectedSet && !visibleSets.includes(selectedSet) ? [...visibleSets, selectedSet] : visibleSets;
  const stepIndex = preview ? 3 : setId ? (kind === "full" || tenantId !== null ? 2 : 1) : 0;
  const stepDefs = [
    { label: t("restore.rail.kind"), sub: selectedSet ? t("restore.rail.kindValue", { kind: t(`restore.kindShort.${kind}`), time: formatDateTime(selectedSet.snapshot_at, locale) }) : t(`restore.kindShort.${kind}`) },
    { label: t("restore.rail.target"), sub: kind === "full" ? (profiles.find((p) => p.id === profileId)?.name ?? t("restore.targetProfileDefault")) : (selectedTenant?.name ?? "—") },
    { label: t("restore.rail.preview"), sub: preview ? (preview.blockers.length ? t("restore.rail.blocked") : t("restore.rail.checked")) : t("restore.rail.previewHint") },
    { label: t("restore.rail.confirm"), sub: t("restore.rail.confirmHint") },
  ];

  const restoreRows = [
    ...history.map((job) => ({ id: `r-${job.id}`, at: job.created_at, archive: job.archive_name, kind: t(`restore.kindShort.${job.kind}`),
      state: <Badge variant={RESTORE_VARIANTS[job.state]}>{t(`restoreState.${job.state}`)}</Badge>, result: restoreResult(t, job), actor: job.requested_by_email ?? "—",
      action: () => setWatching(job.id) })),
    ...tests.map((job) => ({ id: `t-${job.id}`, at: job.created_at, archive: job.backup_set?.archive_name ?? "—", kind: t("restore.kindShort.restore_test"),
      state: <Badge variant={JOB_VARIANTS[job.state]}>{t(`state.${job.state}`)}</Badge>, result: testResult(t, job), actor: job.trigger === "manual" ? (job.requested_by_email ?? "—") : t(`trigger.${job.trigger}`),
      action: null as null | (() => void) })),
  ].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 15);

  return (
    <div className="backup-restore-view">
      {watching ? <RestorePanel t={t} locale={locale} restoreId={watching} isOwner={isOwner} onChanged={async () => { await onChanged(); await loadHistory(); }} /> : null}
      {isOwner ? (
        <section className="card backup-wizard" aria-labelledby="backup-wizard-title">
          <aside className="backup-wizard-rail">
            <span className="backup-kicker" id="backup-wizard-title">{t("restore.wizardTitle")}</span>
            <ol className="backup-rail">
              {stepDefs.map((step, index) => (
                <li key={step.label} className={index < stepIndex ? "backup-rail-step backup-rail-done" : index === stepIndex ? "backup-rail-step backup-rail-current" : "backup-rail-step"}
                  aria-current={index === stepIndex ? "step" : undefined}>
                  <span className="backup-rail-mark" aria-hidden="true">{index < stepIndex ? "✓" : index + 1}</span>
                  <span className="backup-rail-text"><strong>{step.label}</strong><span className="muted backup-small">{step.sub}</span></span>
                </li>
              ))}
            </ol>
            <p className="backup-rail-note muted backup-small">{t("restore.passkeyHelp")}</p>
          </aside>
          <form className="backup-wizard-body" onSubmit={submit}>
            <fieldset className="backup-fieldset">
              <legend className="backup-step">{t("restore.step1")}</legend>
              <div className="backup-choice-grid" role="radiogroup" aria-label={t("restore.kindLabel")}>
                {(["tenant_copy", "full"] as RestoreKind[]).map((value) => (
                  <label key={value} className={kind === value ? "backup-choice backup-choice-on" : "backup-choice"}>
                    <input type="radio" name="backup-restore-kind" value={value} checked={kind === value} onChange={() => setKind(value)} className="backup-choice-input" />
                    <span className="backup-choice-text">
                      <strong>{value === "full" ? t("restore.kindFull") : t("restore.kindTenant")}</strong>
                      <span className="muted backup-small">{value === "full" ? t("restore.kindFullHelp") : t("restore.kindTenantHelp")}</span>
                      <Badge variant={value === "full" ? "danger" : "success"}>{value === "full" ? t("restore.tagMaintenance") : t("restore.tagLowRisk")}</Badge>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset className="backup-fieldset">
              <legend className="backup-step backup-step-row"><span>{t("restore.backupPoint")}</span></legend>
              <p className="muted backup-small">{t("restore.pointHint")}</p>
              {sets.length === 0 ? <p className="muted">{t("restore.noBackups")}</p> : (
                <div className="backup-points" role="radiogroup" aria-label={t("restore.backupPoint")}>
                  {shownSets.map((item) => (
                    <label key={item.id} className={setId === item.id ? "backup-point backup-point-on" : "backup-point"}>
                      <input type="radio" name="backup-restore-point" value={item.id} checked={setId === item.id} onChange={() => setSetId(item.id)} />
                      <span className="backup-point-main">
                        <strong>{formatDateTime(item.snapshot_at, locale)} <span className="muted">· {ageText(t, item.snapshot_at, now)}</span></strong>
                        <span className="backup-mono-ellipsis">{item.archive_name}</span>
                      </span>
                      <span className="muted backup-small backup-nowrap">{t("history.objects", { count: item.object_count })}</span>
                      <span className="backup-badges backup-point-badges">{setBadges(t, item).map((badge) => <Badge key={badge.label} variant={badge.variant}>{badge.label}</Badge>)}</span>
                    </label>
                  ))}
                </div>
              )}
              {sets.length > POINTS_SHOWN ? (
                <button type="button" className="button-ghost" aria-expanded={showAll} onClick={() => setShowAll((value) => !value)}>
                  {showAll ? t("restore.showFewer") : t("restore.showAll", { count: sets.length })}
                </button>
              ) : null}
            </fieldset>

            <fieldset className="backup-fieldset">
              <legend className="backup-step">{t("restore.step2")}</legend>
              {kind === "tenant_copy" ? (
                <div className="backup-stack">
                  {!setId ? <p className="muted">{t("restore.pickPointFirst")}</p> : tenantCards ? (
                    <div className="backup-choice-grid backup-tenant-grid" role="radiogroup" aria-label={t("restore.tenant")}>
                      {tenants.length === 0 ? <p className="muted">{t("restore.noTenants")}</p> : tenants.map((tenant) => (
                        <label key={tenant.id} className={tenantId === tenant.id ? "backup-choice backup-choice-on" : "backup-choice"}>
                          <input type="radio" name="backup-restore-tenant" value={tenant.id} checked={tenantId === tenant.id} className="backup-choice-input"
                            onChange={() => { setTenantId(tenant.id); setNewName(t("restore.copyName", { name: tenant.name })); }} />
                          <span className="backup-choice-text"><strong>{tenant.name}</strong>
                            <span className="muted backup-small">{t("restore.tenantMeta", { users: tenant.users, size: formatFileSize(tenant.bytes, locale) })}</span></span>
                        </label>
                      ))}
                    </div>
                  ) : (
                    <label className="field-stack">
                      <span className="field-label">{t("restore.tenant")}</span>
                      <SearchableSelect<BackupTenant, number>
                        options={tenants}
                        value={tenantId}
                        getId={(item) => item.id}
                        getLabel={(item) => t("restore.tenantLabel", { name: item.name, users: item.users, size: formatFileSize(item.bytes, locale) })}
                        onChange={(item) => { setTenantId(item?.id ?? null); if (item) setNewName(t("restore.copyName", { name: item.name })); }}
                        placeholder={t("restore.tenantPlaceholder")}
                        emptyLabel={t("restore.noTenants")}
                      />
                    </label>
                  )}
                  <label className="field-stack backup-field-narrow">
                    <span className="field-label">{t("restore.newName")}</span>
                    <input className="input" value={newName} maxLength={200} onChange={(event) => setNewName(event.target.value)} />
                    <span className="field-help">{t("restore.newNameHelp")}</span>
                  </label>
                </div>
              ) : (
                <div className="backup-stack">
                  <label className="field-stack backup-field-narrow">
                    <span className="field-label">{t("restore.targetProfile")}</span>
                    <SearchableSelect<StorageOverview["profiles"][number], string>
                      options={profiles}
                      value={profileId}
                      getId={(item) => item.id}
                      getLabel={(item) => item.is_active ? t("restore.profileActive", { name: item.name }) : item.name}
                      onChange={(item) => setProfileId(item?.id ?? null)}
                      placeholder={t("restore.targetProfileDefault")}
                      nullLabel={t("restore.targetProfileDefault")}
                    />
                    <span className="field-help">{t("restore.targetProfileHelp")}</span>
                  </label>
                  <StatusBanner tone="error" message={t("restore.fullWarning")} />
                </div>
              )}
            </fieldset>

            <fieldset className="backup-fieldset">
              <legend className="backup-step backup-step-row"><span>{t("restore.step3")}</span></legend>
              <div className="table-actions">
                <button type="button" className="button-secondary" disabled={!canPreview || working} onClick={() => void loadPreview()}>{preview ? t("actions.previewRefresh") : t("actions.preview")}</button>
              </div>
              {preview ? <PreviewFacts t={t} locale={locale} preview={preview} /> : <p className="backup-empty-box muted">{t("restore.previewHint")}</p>}
            </fieldset>

            {preview && preview.blockers.length === 0 ? (
              <fieldset className="backup-fieldset backup-confirm">
                <legend className="backup-step">{t("restore.step4")}</legend>
                {kind === "full" ? (
                  <>
                    <label className="checkbox-row"><input type="checkbox" checked={skipRescue} onChange={(event) => setSkipRescue(event.target.checked)} /><span>{t("restore.skipRescue")}</span></label>
                    {skipRescue ? (
                      <label className="field-stack backup-field-narrow">
                        <span className="field-label">{t("restore.skipRescueReason")}</span>
                        <textarea className="input" rows={2} maxLength={500} value={skipReason} onChange={(event) => setSkipReason(event.target.value)} />
                      </label>
                    ) : null}
                  </>
                ) : null}
                {/* Löschjournal (Datenschutz-Audit PRIV-010): standardmässig an, aus nur mit Begründung */}
                <label className="checkbox-row"><input type="checkbox" checked={replayErasures} onChange={(event) => setReplayErasures(event.target.checked)} /><span>{t("restore.replayErasures")}</span></label>
                <p className="field-help">{t("restore.replayErasuresHint")}</p>
                {!replayErasures ? (
                  <label className="field-stack backup-field-narrow">
                    <span className="field-label">{t("restore.replayErasuresReason")}</span>
                    <textarea className="input" rows={2} maxLength={500} value={replayReason} onChange={(event) => setReplayReason(event.target.value)} />
                  </label>
                ) : null}
                <p className="muted">{t("restore.phraseExplain")}</p>
                <div className="backup-confirm-row">
                  <label className="field-stack backup-field-narrow">
                    <span className="field-label">{t("restore.confirmationLabel", { phrase: preview.confirmation_phrase })}</span>
                    <input className={phraseOk ? "input backup-mono backup-phrase-ok" : "input backup-mono"} value={confirmation} autoComplete="off" spellCheck={false}
                      placeholder={preview.confirmation_phrase} onKeyDown={blockEnter} onChange={(event) => setConfirmation(event.target.value)} />
                    <span className="field-help">{t("restore.passkeyHelp")}</span>
                  </label>
                  <button type="submit" className={kind === "full" ? "button-danger" : "button-primary"} disabled={!canSubmit || working}>
                    {kind === "full" ? t("actions.startFullRestore") : t("actions.startTenantRestore")}
                  </button>
                </div>
              </fieldset>
            ) : null}
          </form>
        </section>
      ) : <StatusBanner tone="neutral" message={t("restore.ownerOnly")} />}

      <section className="card" aria-labelledby="backup-restore-history">
        <h2 id="backup-restore-history" className="backup-section-title">{t("restore.historyTitle")}</h2>
        <DataTable columns={[t("columns.time"), t("columns.kind"), t("columns.state"), t("columns.result"), t("columns.actor"), t("columns.actions")]} emptyMessage={t("restore.historyEmpty")}>
          {restoreRows.map((row) => (
            <tr key={row.id}>
              <td><div className="backup-strong backup-nowrap">{formatDateTime(row.at, locale)}</div><div className="backup-mono-ellipsis muted" title={row.archive}>{row.archive}</div></td>
              <td>{row.kind}</td>
              <td>{row.state}</td>
              <td>{row.result}</td>
              <td className="muted">{row.actor}</td>
              <td>{row.action ? <button type="button" className="button-secondary" onClick={row.action}>{t("actions.details")}</button> : null}</td>
            </tr>
          ))}
        </DataTable>
      </section>
    </div>
  );
}

function restoreResult(t: TFunc, job: RestoreJob): string {
  const result = (job.result ?? {}) as Record<string, unknown>;
  if (job.state === "completed" && job.kind === "tenant_copy") return t("restore.resultTenant", { name: String(result.tenant_name ?? ""), files: Number(result.files_imported ?? 0) });
  if (job.state === "completed") return t("restore.resultFull", { generation: Number(result.generation ?? 0) });
  if (job.state === "rolled_back") return t("restore.resultRolledBack");
  if (job.state === "failed" || job.state === "interrupted") return errorText(t, job.error_code, job.error_message);
  return t(`restoreState.${job.state}`);
}

function testResult(t: TFunc, job: BackupJob): string {
  const summary = job.summary ?? {};
  if (job.state === "completed") return typeof summary.contents_checked === "number"
    ? t("restore.resultTestPassed", { count: summary.contents_checked }) : t("restore.resultTestPassedShort");
  if (job.state === "failed" || job.state === "interrupted") return errorText(t, job.error_code, job.error_message);
  return t(`state.${job.state}`);
}

function PreviewFacts({ t, locale, preview }: { t: TFunc; locale: string; preview: RestorePreview }) {
  const set = preview.backup_set;
  return (
    <div className="backup-stack">
      <div className="backup-preview">
        <dl className="storage-facts backup-preview-facts">
          <dt>{t("detail.archive")}</dt><dd className="backup-id">{set.archive_name}</dd>
          <dt>{t("detail.snapshot")}</dt><dd>{formatDateTime(set.snapshot_at, locale)}</dd>
          <dt>{t("detail.version")}</dt><dd>{t("detail.versionValue", { app: set.app_version ?? "—", schema: preview.schema_revision ?? "—" })}</dd>
          <dt>{t("preview.schema")}</dt><dd>{t(`schema.${preview.schema_state}`)}</dd>
          {preview.kind === "full" ? (<><dt>{t("preview.target")}</dt><dd>{preview.target_profile_name ?? "—"}</dd></>) : null}
          {preview.tenant ? (<><dt>{t("restore.tenant")}</dt><dd>{preview.tenant.name}</dd></>) : null}
          {preview.new_name ? (<><dt>{t("restore.newName")}</dt><dd>{preview.new_name}</dd></>) : null}
          <dt>{t("preview.size")}</dt><dd>{formatFileSize(preview.estimated_bytes, locale)}</dd>
        </dl>
        <div className="backup-preview-steps">
          <span className="backup-label">{t("preview.steps")}</span>
          <ol className="backup-numbered">
            {preview.steps.map((step, index) => <li key={step}><span className="backup-mono backup-step-n" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>{t.has(`step.${step}`) ? t(`step.${step}`) : step}</li>)}
          </ol>
        </div>
      </div>
      {preview.blockers.map((code) => <StatusBanner key={code} tone="error" message={t.has(`blocker.${code}`) ? t(`blocker.${code}`) : code} />)}
      <ul className="backup-risks">
        {preview.risks.map((code) => <li key={code} className="backup-risk">{t.has(`risk.${code}`) ? t(`risk.${code}`) : code}</li>)}
      </ul>
    </div>
  );
}
