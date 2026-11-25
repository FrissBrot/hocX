"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import {
  apiErrorCode,
  startCloudLogin,
  type CloudNode,
  type CloudProvider,
  type CloudProviderKey,
  type ImportJob,
  usesCredentials,
} from "@/lib/files/file-import";
import { formatFileSize, formatInteger } from "@/lib/utils/format";

import { ImportCloudTree } from "./import-cloud-tree";
import { ImportWebdavForm } from "./import-webdav-form";

const POLL_MS = 3000;
// Microsoft Entra: Tenant-ID (GUID) oder verifizierte Domain des Vereins-Tenants
const TENANT_HINT = /^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+)$/i;

type Props = {
  job: ImportJob;
  provider: CloudProvider | null;
  returnError: string | null;
  onJob: (job: ImportJob) => void;
  onCancelled: () => void | Promise<void>;
};

/** Anmelden, Ordner wählen und Auflisten für API-Quellen (Plan P1, Wizard-Schritte 3-5). */
export function ImportCloudStep({ job, provider, returnError, onJob, onCancelled }: Props) {
  const t = useTranslations("fileImport");
  const locale = useLocale();
  const showToast = useToast();
  const confirm = useConfirm();
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Map<string, CloudNode>>(new Map());
  const source = job.source as CloudProviderKey;
  const connection = job.connection ?? null;
  const connected = connection?.status === "active";
  const listing = job.status === "listing";
  const credentials = usesCredentials(provider);
  // WebDAV: «Anderes Konto» zeigt das Formular erneut (statt einer OAuth-Anmeldung)
  const [otherAccount, setOtherAccount] = useState(false);

  useEffect(() => {
    if (!listing) return;
    let stopped = false;
    const timer = window.setInterval(async () => {
      try {
        const next = await browserApiFetch<ImportJob>(`/api/cloud-import/jobs/${job.id}`);
        if (!stopped) onJob(next);
      } catch {
        // nächster Takt
      }
    }, POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [job.id, listing, onJob]);

  function errorText(error: unknown): string {
    const code = apiErrorCode(error);
    if (code && t.has(`cloud.errors.${code}`)) return t(`cloud.errors.${code}`);
    return code && t.has(`errors.${code}`) ? t(`errors.${code}`) : t("errors.generic");
  }

  async function login(options: { tier?: string | null; selectAccount?: boolean } = {}) {
    setBusy(true);
    try {
      await startCloudLogin(browserApiFetch, job.id, source, options);
    } catch (error) {
      showToast(errorText(error), "error");
      setBusy(false);
    }
  }

  async function disconnect() {
    const ok = await confirm({ tone: "danger", message: t("cloud.disconnectConfirm"), confirmLabel: t("cloud.disconnect") });
    if (!ok) return;
    try {
      onJob(await browserApiFetch<ImportJob>(`/api/cloud-import/jobs/${job.id}/disconnect`, { method: "POST" }));
      setSelected(new Map());
    } catch (error) {
      showToast(errorText(error), "error");
    }
  }

  async function analyse() {
    setBusy(true);
    try {
      onJob(
        await browserApiFetch<ImportJob>(`/api/cloud-import/jobs/${job.id}/selection`, {
          method: "POST",
          body: JSON.stringify({ refs: Array.from(selected.keys()) }),
        }),
      );
    } catch (error) {
      showToast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    const ok = await confirm({ tone: "danger", message: t("cancel.draftConfirm"), confirmLabel: t("cancel.label") });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/cloud-import/jobs/${job.id}/cancel`, { method: "POST" });
      await onCancelled();
    } catch (error) {
      showToast(errorText(error), "error");
    }
  }

  function toggle(node: CloudNode, checked: boolean) {
    setSelected((current) => {
      const next = new Map(current);
      if (checked) next.set(node.ref, node);
      else next.delete(node.ref);
      return next;
    });
  }

  const providerName = t(`source.provider.${source}`);
  const errorCode = returnError ?? job.error;

  if (listing) {
    return (
      <section className="section-card file-import-card" aria-live="polite">
        <h2 className="section-title">{t("cloud.listingTitle")}</h2>
        <p className="muted">{t("cloud.listingHint")}</p>
        <progress className="gallery-upload-progress" aria-label={t("cloud.listingTitle")} />
        <p className="file-import-listing-summary">
          {t("cloud.listingProgress", {
            count: job.total_items,
            size: formatFileSize(job.total_bytes, locale),
            folders: formatInteger(job.listing?.folders ?? 0, locale),
          })}
        </p>
        {job.not_before ? <StatusBanner tone="neutral" message={t("cloud.throttled")} /> : null}
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={() => void cancel()}>{t("cancel.label")}</button>
        </div>
      </section>
    );
  }

  return (
    <section className="section-card file-import-card">
      <h2 className="section-title">{t("cloud.title", { provider: providerName })}</h2>
      {errorCode ? (
        <StatusBanner tone="warning" message={t.has(`cloud.errors.${errorCode}`) ? t(`cloud.errors.${errorCode}`) : t("errors.generic")} />
      ) : null}
      {errorCode === "admin_consent_required" || provider?.info.admin_consent_url ? (
        <AdminConsentHelp provider={provider} open={errorCode === "admin_consent_required"} />
      ) : null}
      {credentials && (!connected || otherAccount) ? (
        <>
          <p className="muted">{t(`cloud.connectHint.${source}`)}</p>
          <ImportWebdavForm
            jobId={job.id}
            onJob={(next) => {
              setOtherAccount(false);
              setSelected(new Map());
              onJob(next);
            }}
            onCancel={otherAccount ? () => setOtherAccount(false) : () => void cancel()}
            cancelLabel={otherAccount ? t("cloud.webdav.back") : undefined}
          />
        </>
      ) : !connected ? (
        <>
          <p className="muted">{t(`cloud.connectHint.${source}`)}</p>
          <p className="field-help">{t("cloud.privacy")}</p>
          <div className="modal-actions">
            <button type="button" className="button-ghost" disabled={busy} onClick={() => void cancel()}>{t("cancel.label")}</button>
            <button type="button" className="button-primary" disabled={busy || !provider} onClick={() => void login({ tier: provider?.default_tier })}>
              {t("cloud.connect", { provider: providerName })}
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="file-import-cloud-account">
            <span>{t("cloud.connectedAs", { account: connection?.account_label ?? providerName })}</span>
            <button type="button" className="button-secondary button-ghost" disabled={busy} onClick={() => (credentials ? setOtherAccount(true) : void login({ tier: connection?.tier, selectAccount: true }))}>
              {t("cloud.otherAccount")}
            </button>
            <button type="button" className="button-secondary button-ghost" disabled={busy} onClick={() => void disconnect()}>
              {t("cloud.disconnect")}
            </button>
          </div>
          <p className="muted">{t("cloud.chooseHint")}</p>
          <ImportCloudTree jobId={job.id} selected={selected} onToggle={toggle} onRequestTier={(tier) => void login({ tier })} />
          <p className="file-import-listing-summary">{t("cloud.selected", { count: selected.size })}</p>
          <div className="modal-actions">
            <button type="button" className="button-ghost" disabled={busy} onClick={() => void cancel()}>{t("cancel.label")}</button>
            <button type="button" className="button-primary" disabled={busy || selected.size === 0} onClick={() => void analyse()}>
              {t("cloud.analyse")}
            </button>
          </div>
        </>
      )}
    </section>
  );
}

/** Hilfe, wenn die Organisation des Kontos Apps erst nach Freigabe durch ihre IT zulässt. */
function AdminConsentHelp({ provider, open }: { provider: CloudProvider | null; open: boolean }) {
  const t = useTranslations("fileImport");
  const showToast = useToast();
  const [tenant, setTenant] = useState("");
  const template = provider?.info.admin_consent_url ?? null;
  const valid = TENANT_HINT.test(tenant.trim());
  const link = template && valid ? template.replace("{tenant}", encodeURIComponent(tenant.trim().toLowerCase())) : null;

  async function copy() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      showToast(t("cloud.adminConsent.copied"), "success");
    } catch {
      showToast(t("errors.generic"), "error");
    }
  }

  return (
    <details className="file-import-consent-help" open={open}>
      <summary>{t("cloud.adminConsent.title")}</summary>
      <p>{t("cloud.adminConsent.explain")}</p>
      <ol className="file-import-consent-steps">
        <li>{t("cloud.adminConsent.step1")}</li>
        <li>{t("cloud.adminConsent.step2")}</li>
        <li>{t("cloud.adminConsent.step3")}</li>
      </ol>
      {template ? (
        <>
          <label className="field-stack">
            <span className="field-label">{t("cloud.adminConsent.tenantLabel")}</span>
            <input value={tenant} onChange={(event) => setTenant(event.target.value)} autoComplete="off" spellCheck={false} />
            <span className="field-help">{t("cloud.adminConsent.tenantHelp")}</span>
          </label>
          {link ? (
            <div className="file-import-consent-link">
              <a href={link} target="_blank" rel="noopener noreferrer">{t("cloud.adminConsent.open")}</a>
              <button type="button" className="button-secondary" onClick={() => void copy()}>{t("cloud.adminConsent.copy")}</button>
            </div>
          ) : null}
        </>
      ) : null}
    </details>
  );
}
