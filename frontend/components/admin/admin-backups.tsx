"use client";

import { useCallback, useRef, useState } from "react";
import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { StatusBanner } from "@/components/ui/status-banner";
import { Tabs } from "@/components/ui/tabs";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { useVisibleInterval } from "@/lib/hooks/use-visible-interval";
import type { BackupJob, BackupJobKind, BackupSettings, BackupStatus } from "@/types/api";

import { History, HISTORY_FILTERS, HISTORY_KINDS, type HistoryFilter } from "./backup-admin/history";
import { Overview, type BackupActions } from "./backup-admin/overview";
import { Restore } from "./backup-admin/restore";
import { Settings } from "./backup-admin/settings";
import { ACTIVE_POLL_MS, IDLE_POLL_MS } from "./backup-admin/shared";

// Backup-Redesign 1.6 (Plan audit-reports/plans/2026-11-25-backup-admin-redesign.md): vier Reiter,
// Zustand in der URL (nur Codes und Auftrags-IDs, DESIGN.md §11). Für Support-Admins liefert die
// API weder Adresse/Benutzer der Storage Box noch rohe Fehlermeldungen.
export { useIdempotencyKey } from "./backup-admin/shared";

const TABS = ["overview", "history", "restore", "settings"] as const;
type BackupTab = (typeof TABS)[number];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function pick<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
}

export function AdminBackups({ initialStatus, initialSettings, isOwner }: { initialStatus: BackupStatus; initialSettings: BackupSettings; isOwner: boolean }) {
  const t = useTranslations("adminBackups");
  const locale = useLocale();
  const showToast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState(initialStatus);
  const [settings, setSettings] = useState(initialSettings);
  const [busy, setBusy] = useState<string | null>(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  const loadingRef = useRef(false);

  const params = new URLSearchParams(searchParams?.toString() ?? "");
  const tab = pick(params.get("tab"), TABS, "overview");
  const historyState = pick<HistoryFilter>(params.get("state"), HISTORY_FILTERS, "all");
  const historyKind = pick<BackupJobKind | "">(params.get("kind"), [...HISTORY_KINDS, ""], "");
  const offset = Math.max(0, Number.parseInt(params.get("offset") ?? "0", 10) || 0);
  const jobParam = params.get("job");
  const job = jobParam && UUID.test(jobParam) ? jobParam : null;

  const navigate = useCallback((patch: Record<string, string | null>) => {
    const next = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(patch)) {
      if (value === null || value === "" || (key === "tab" && value === "overview")) next.delete(key);
      else next.set(key, value);
    }
    const query = next.toString();
    router.replace((query ? `${pathname}?${query}` : pathname) as Route, { scroll: false });
  }, [pathname, router]);

  const reload = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    try {
      setStatus(await browserApiFetch<BackupStatus>("/api/admin/backups/status"));
    } catch {
      // Letzten Stand weiter zeigen.
    } finally {
      loadingRef.current = false;
    }
  }, []);

  const active = status.current_job !== null || status.current_restore !== null;
  // Pausiert in Hintergrund-Tabs und lädt beim Zurückkehren sofort nach.
  useVisibleInterval(() => void reload(), active ? ACTIVE_POLL_MS : IDLE_POLL_MS);

  const start = useCallback(async (kind: "backup" | "restoreTest") => {
    setBusy(kind);
    try {
      const path = kind === "backup" ? "/api/admin/backups" : "/api/admin/backups/restore-test";
      await browserApiFetch<BackupJob>(path, { method: "POST", body: JSON.stringify({ idempotency_key: `${kind}-${Date.now()}` }) });
      showToast(kind === "backup" ? t("toast.backupQueued") : t("toast.restoreTestQueued"), "success");
      await reload();
      setHistoryVersion((value) => value + 1);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setBusy(null);
    }
  }, [reload, showToast, t]);

  const verifyJob = useCallback(async (jobId: string) => {
    setBusy("verify");
    try {
      await browserApiFetch(`/api/admin/backups/${encodeURIComponent(jobId)}/verify`, { method: "POST", body: JSON.stringify({ idempotency_key: `verify-${jobId}-${Date.now()}` }) });
      showToast(t("toast.verifyQueued"), "success");
      await reload();
      setHistoryVersion((value) => value + 1);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.failed"), "error");
    } finally {
      setBusy(null);
    }
  }, [reload, showToast, t]);

  const actions: BackupActions = {
    startBackup: () => start("backup"),
    startRestoreTest: () => start("restoreTest"),
    verifyJob,
    busy,
  };
  const actionsDisabled = busy !== null || !status.enabled || status.current_job !== null;

  return (
    <div className="grid backup-page">
      <div className="page-header backup-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("description")}</p>
        </div>
        {isOwner ? (
          <div className="backup-header-actions">
            <button type="button" className="button-secondary" disabled={actionsDisabled} onClick={() => void start("restoreTest")}>{t("actions.restoreTest")}</button>
            <button type="button" className="button-primary" disabled={actionsDisabled} onClick={() => void start("backup")}>{t("actions.backupNow")}</button>
          </div>
        ) : null}
      </div>
      {!isOwner ? <StatusBanner tone="neutral" message={t("banner.readOnly")} /> : null}
      {!status.enabled ? <StatusBanner tone="neutral" message={t("banner.disabled")} /> : null}
      {status.enabled && !status.worker_alive ? <StatusBanner tone="error" message={t("banner.workerDown")} /> : null}
      <Tabs
        activeId={tab}
        onChange={(id) => navigate({ tab: id, job: null })}
        tabs={[
          { id: "overview", label: t("tabs.overview"), count: status.problems.length || null, countTone: status.overall === "critical" ? "danger" : undefined,
            content: <Overview t={t} locale={locale} status={status} settings={settings} isOwner={isOwner} onChanged={reload} navigate={navigate} actions={actions} /> },
          { id: "history", label: t("tabs.history"),
            content: <History t={t} locale={locale} isOwner={isOwner} status={status} params={{ state: historyState, kind: historyKind, offset, job }} navigate={navigate} actions={actions} version={historyVersion} /> },
          { id: "restore", label: t("tabs.restore"), content: <Restore t={t} locale={locale} isOwner={isOwner} status={status} onChanged={reload} /> },
          { id: "settings", label: t("tabs.settings"), content: <Settings t={t} locale={locale} settings={settings} isOwner={isOwner} onSaved={setSettings} /> },
        ]}
      />
    </div>
  );
}
