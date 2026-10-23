"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatDateTime, formatFileSize } from "@/lib/utils/format";

const MIN_PASSWORD_LENGTH = 12;
const API = "/api/tenant-data-exports";

type ExportStatus = "queued" | "running" | "done" | "failed" | "expired";

type TenantDataExport = {
  id: string;
  status: ExportStatus;
  include_files: boolean;
  created_at: string;
  finished_at: string | null;
  expires_at: string | null;
  size_bytes: number | null;
  missing_files: number;
};

const STATUS_VARIANT: Record<ExportStatus, "info" | "success" | "danger" | "neutral"> = {
  queued: "info",
  running: "info",
  done: "success",
  failed: "danger",
  expired: "neutral",
};

// Vereinsexport (Datenschutz-Audit Paket 6): alle Vereinsdaten als AES-ZIP für die Weiterarbeit.
// Wird im Hintergrund gebaut und ist danach 7 Tage abrufbar.
export function TenantDataExportPanel() {
  const t = useTranslations("tenantSettings.privacy.export");
  const locale = useLocale();
  const toast = useToast();
  const [exports, setExports] = useState<TenantDataExport[]>([]);
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [includeFiles, setIncludeFiles] = useState(true);
  const [busy, setBusy] = useState(false);
  const valid = password.length >= MIN_PASSWORD_LENGTH && password === repeat;
  const active = exports.some((item) => item.status === "queued" || item.status === "running");

  const load = useCallback(async () => {
    try {
      setExports(await browserApiFetch<TenantDataExport[]>(API));
    } catch {
      // Liste ist optional; ein Fehler zeigt sich beim Bestellen
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void load(), 10_000);
    return () => window.clearInterval(timer);
  }, [active, load]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid) return;
    setBusy(true);
    try {
      await browserApiFetch<TenantDataExport>(API, { method: "POST", body: JSON.stringify({ password, include_files: includeFiles }) });
      setPassword("");
      setRepeat("");
      toast(t("queued"), "success");
      await load();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("failed"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card docverify-card">
      <div className="docverify-card-head">
        <h2 className="docverify-heading">{t("title")}</h2>
      </div>
      <p className="muted">{t("description")}</p>
      <form className="grid" onSubmit={(event) => void submit(event)}>
        <label className="checkbox-row">
          <input type="checkbox" checked={includeFiles} onChange={(event) => setIncludeFiles(event.target.checked)} />
          <span>{t("includeFiles")}</span>
        </label>
        <label className="field-stack">
          <span className="field-label">{t("password")}</span>
          <input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} />
          <span className="field-help">{t("passwordHelp", { min: MIN_PASSWORD_LENGTH })}</span>
        </label>
        <label className="field-stack">
          <span className="field-label">{t("repeat")}</span>
          <input type="password" autoComplete="new-password" value={repeat} onChange={(event) => setRepeat(event.target.value)} />
          {repeat && password !== repeat ? <span className="field-help">{t("mismatch")}</span> : null}
        </label>
        <p className="field-help">{t("hint")}</p>
        <div className="table-actions table-actions-start">
          <button type="submit" className="button-primary" disabled={!valid || busy || active}>
            {t("start")}
          </button>
        </div>
      </form>
      {exports.length ? (
        <ul className="tenant-export-list">
          {exports.map((item) => (
            <li key={item.id} className="tenant-export-item">
              <Badge variant={STATUS_VARIANT[item.status]}>{t(`status.${item.status}`)}</Badge>
              <span>{formatDateTime(item.created_at, locale)}</span>
              {item.status === "done" ? (
                <>
                  <span className="muted">
                    {formatFileSize(item.size_bytes)} · {t("expires", { date: formatDateTime(item.expires_at, locale) })}
                  </span>
                  {item.missing_files ? <span className="muted">{t("missingFiles", { count: item.missing_files })}</span> : null}
                  <a className="button-secondary" href={`${browserApiBaseUrl}${API}/${item.id}/download`}>
                    {t("download")}
                  </a>
                </>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
