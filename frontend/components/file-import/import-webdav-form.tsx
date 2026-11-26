"use client";

import { FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { Select } from "@/components/ui/select";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { docsUrl } from "@/lib/docs";
import { apiErrorCode, webdavConnectBody, type ImportJob, type WebdavPreset } from "@/lib/files/file-import";

type Props = {
  jobId: string;
  onJob: (job: ImportJob) => void;
  /** Bei «Passwort neu eingeben»: Erklärung oben, Vorlage/Adresse unverändert lassen. */
  reenter?: boolean;
  onCancel?: () => void;
  /** Beschriftung der Nebenaktion (Standard: «Import verwerfen»). */
  cancelLabel?: string;
};

/**
 * Zugangsdaten für WebDAV (kDrive, Nextcloud, andere). Das Passwort lebt nur in diesem Formular und
 * im Request-Body; das Backend prüft die Adresse (SSRF-Schutz) und die Zugangsdaten, bevor es sie
 * verschlüsselt speichert.
 */
export function ImportWebdavForm({ jobId, onJob, reenter = false, onCancel, cancelLabel }: Props) {
  const t = useTranslations("fileImport");
  const [preset, setPreset] = useState<WebdavPreset>("kdrive");
  const [server, setServer] = useState("");
  const [kdriveId, setKdriveId] = useState("");
  const [url, setUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const help = docsUrl("dateiImport", "app-passwort");

  const complete =
    username.trim() !== "" &&
    password !== "" &&
    (preset === "kdrive" || (preset === "nextcloud" ? server.trim() !== "" : url.trim() !== ""));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!complete || busy) return;
    setBusy(true);
    setError(null);
    try {
      const job = await browserApiFetch<ImportJob>(`/api/cloud-import/jobs/${jobId}/webdav/connect`, {
        method: "POST",
        body: JSON.stringify(webdavConnectBody({ preset, server, kdriveId, url, username, password })),
      });
      setPassword("");
      onJob(job);
    } catch (caught) {
      const code = apiErrorCode(caught);
      setError(code && t.has(`cloud.errors.${code}`) ? t(`cloud.errors.${code}`) : t("cloud.errors.generic"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="file-import-webdav" onSubmit={(event) => void submit(event)} aria-busy={busy}>
      {reenter ? <p className="muted">{t("cloud.webdav.reenterHint")}</p> : null}
      {error ? <StatusBanner tone="warning" message={error} /> : null}
      <div className="grid file-import-webdav-fields">
        <label className="field-stack">
          <span className="field-label">{t("cloud.webdav.preset")}</span>
          <Select value={preset} onChange={(event) => setPreset(event.target.value as WebdavPreset)} disabled={busy}>
            <option value="kdrive">{t("cloud.webdav.presetKdrive")}</option>
            <option value="nextcloud">{t("cloud.webdav.presetNextcloud")}</option>
            <option value="generic">{t("cloud.webdav.presetGeneric")}</option>
          </Select>
        </label>
        {preset === "kdrive" ? (
          <label className="field-stack">
            <span className="field-label">{t("cloud.webdav.kdriveId")}</span>
            <input value={kdriveId} onChange={(event) => setKdriveId(event.target.value)} inputMode="numeric" autoComplete="off" disabled={busy} />
            <span className="field-help">{t("cloud.webdav.kdriveIdHelp")}</span>
          </label>
        ) : null}
        {preset === "nextcloud" ? (
          <label className="field-stack">
            <span className="field-label">{t("cloud.webdav.server")}</span>
            <input value={server} onChange={(event) => setServer(event.target.value)} autoComplete="url" spellCheck={false} required disabled={busy} />
            <span className="field-help">{t("cloud.webdav.serverHelp")}</span>
          </label>
        ) : null}
        {preset === "generic" ? (
          <label className="field-stack">
            <span className="field-label">{t("cloud.webdav.url")}</span>
            <input type="url" value={url} onChange={(event) => setUrl(event.target.value)} autoComplete="url" spellCheck={false} required disabled={busy} />
            <span className="field-help">{t("cloud.webdav.urlHelp")}</span>
          </label>
        ) : null}
        <label className="field-stack">
          <span className="field-label">{t("cloud.webdav.username")}</span>
          <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" spellCheck={false} required disabled={busy} />
          {preset === "kdrive" ? <span className="field-help">{t("cloud.webdav.usernameHelp")}</span> : null}
        </label>
        <label className="field-stack">
          <span className="field-label">{t("cloud.webdav.password")}</span>
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" required disabled={busy} />
          <span className="field-help">{t("cloud.webdav.passwordHelp")}</span>
        </label>
      </div>
      {help ? (
        <p className="field-help">
          <a href={help} target="_blank" rel="noopener noreferrer">{t("cloud.webdav.help")}</a>
        </p>
      ) : null}
      <div className="modal-actions">
        {onCancel ? <button type="button" className="button-ghost" disabled={busy} onClick={onCancel}>{cancelLabel ?? t("cancel.label")}</button> : null}
        <button type="submit" className="button-primary" disabled={busy || !complete}>
          {busy ? t("cloud.webdav.connecting") : t("cloud.webdav.connect")}
        </button>
      </div>
    </form>
  );
}
