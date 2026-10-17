"use client";

import Link from "next/link";
import { useState } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate } from "@/lib/utils/format";

type VerificationRequest = {
  status: "pending" | "approved" | "rejected" | "withdrawn";
  tenant_name: string;
  message: string | null;
  requested_at: string;
  decided_at: string | null;
  decision_note: string | null;
};

export type DocumentVerificationState = {
  show_identity: boolean;
  show_newer_version: boolean;
  tenant_id: string;
  tenant_name: string;
  has_logo: boolean;
  verified_at: string | null;
  revoked_at: string | null;
  revoked_reason: string | null;
  request: VerificationRequest | null;
  verify_base_url: string;
  has_verify_domain_feature: boolean;
  verify_domain: VerifyDomainState | null;
};

// Eigene Prüf-Domain (Feature verify_domain); eingerichtet wird sie unter Domains.
type VerifyDomainState = {
  domain: string;
  status: "pending" | "active";
  is_healthy: boolean;
  // neue PDFs und die Weiterleitung der zentralen Prüfseite verwenden sie
  in_use: boolean;
};

type TFunc = (key: string) => string;

function verifyDomainStatus(state: DocumentVerificationState, t: TFunc): { label: string; variant: "success" | "warning" | "info" | "neutral"; hint: string | null } {
  const domain = state.verify_domain;
  if (!domain) return { label: "", variant: "neutral", hint: null };
  if (!state.has_verify_domain_feature) return { label: t("domainStatusNotBooked"), variant: "warning", hint: t("domainNotBookedHint") };
  if (domain.status === "pending") return { label: t("domainStatusPending"), variant: "info", hint: t("domainPendingHint") };
  if (!state.show_identity) return { label: t("domainStatusHidden"), variant: "warning", hint: t("domainHiddenHint") };
  if (!domain.is_healthy) return { label: t("domainStatusUnhealthy"), variant: "warning", hint: t("domainUnhealthyHint") };
  return { label: t("domainStatusActive"), variant: "success", hint: null };
}

const API = "/api/document-verification";

// Dokumente → Echtheitsprüfung (nur Mandanten-Admins): was die öffentliche Prüfseite über
// Dokumente dieses Vereins zeigt, und die Bestätigung der Organisation durch hocX.
export function DocumentVerificationSettings({ initialState }: { initialState: DocumentVerificationState }) {
  const t = useTranslations("documents.verification");
  const toast = useToast();
  const confirm = useConfirm();
  const [state, setState] = useState(initialState);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function call(path: string, init: RequestInit, success: string) {
    setBusy(true);
    try {
      setState(await browserApiFetch<DocumentVerificationState>(path, init));
      toast(success, "success");
      return true;
    } catch (error) {
      toast(error instanceof Error ? error.message : t("saveFailed"), "error");
      return false;
    } finally {
      setBusy(false);
    }
  }

  const toggle = (key: "show_identity" | "show_newer_version", value: boolean) =>
    call(API, { method: "PATCH", body: JSON.stringify({ [key]: value }) }, t("saved"));

  async function requestVerification() {
    if (await call(`${API}/request`, { method: "POST", body: JSON.stringify({ message: message.trim() || null }) }, t("requestSent"))) {
      setMessage("");
    }
  }

  async function withdraw() {
    const ok = await confirm({ tone: "danger", message: t("withdrawConfirm"), confirmLabel: t("withdraw") });
    if (ok) await call(`${API}/request`, { method: "DELETE" }, t("withdrawn"));
  }

  const pending = state.request?.status === "pending";
  const rejected = !state.verified_at && state.request?.status === "rejected";
  const verifyLink = state.verify_base_url;
  const domainStatus = verifyDomainStatus(state, t);
  const domainInUse = state.verify_domain?.in_use ? state.verify_domain.domain : null;

  return (
    <div className="grid docverify">
      <div className="page-header">
        <h2 className="section-title">{t("title")}</h2>
        <p className="muted">{t("intro")}</p>
      </div>

      <section className="panel docverify-section">
        <h3 className="docverify-heading">{t("publicTitle")}</h3>
        <label className="docverify-check">
          <input type="checkbox" disabled={busy} checked={state.show_identity} onChange={(event) => void toggle("show_identity", event.target.checked)} />
          <span>{t("showIdentity")}</span>
        </label>
        <p className="muted docverify-hint">{t("showIdentityHint")}</p>
        <label className="docverify-check">
          <input type="checkbox" disabled={busy} checked={state.show_newer_version} onChange={(event) => void toggle("show_newer_version", event.target.checked)} />
          <span>{t("showNewerVersion")}</span>
        </label>
        <p className="muted docverify-hint">{t("showNewerVersionHint")}</p>
        <div>
          <a className="button-secondary" href={verifyLink} target="_blank" rel="noopener noreferrer">{t("openPage")}</a>
        </div>
      </section>

      <section className="panel docverify-section">
        <div className="docverify-status-row">
          <h3 className="docverify-heading">{t("domainTitle")}</h3>
          {state.verify_domain ? (
            <Badge variant={domainStatus.variant} dot>{domainStatus.label}</Badge>
          ) : !state.has_verify_domain_feature ? (
            <Badge variant="neutral">{t("domainStatusNotBooked")}</Badge>
          ) : null}
        </div>
        <p className="muted docverify-hint">{t("domainIntro")}</p>
        <p className="muted docverify-hint">{t("domainLevelHint")}</p>
        {state.verify_domain && <p className="docverify-domain">{state.verify_domain.domain}</p>}
        {domainStatus.hint && <StatusBanner tone="neutral" message={domainStatus.hint} />}
        {!state.verify_domain && !state.has_verify_domain_feature && <StatusBanner tone="neutral" message={t("domainNotBooked")} />}
        {(state.verify_domain || state.has_verify_domain_feature) && (
          <div className="docverify-actions-row">
            <Link className="button-secondary" href="/tenant-settings/domains">
              {state.verify_domain ? t("domainManage") : t("domainSetup")}
            </Link>
          </div>
        )}
      </section>

      <section className="panel docverify-section">
        <div className="docverify-status-row">
          <h3 className="docverify-heading">{t("verificationTitle")}</h3>
          {state.verified_at ? (
            <Badge variant="success" dot>{t("verifiedSince", { date: formatDate(state.verified_at) })}</Badge>
          ) : pending ? (
            <Badge variant="info" dot>{t("pending")}</Badge>
          ) : (
            <Badge variant="neutral">{t("notVerified")}</Badge>
          )}
        </div>
        <p className="muted docverify-hint">{t("verificationExplanation")}</p>
        {state.revoked_reason === "name_changed" && !state.verified_at && (
          <StatusBanner tone="error" message={t("revokedNameChanged", { date: formatDate(state.revoked_at) })} />
        )}
        {state.revoked_reason === "admin" && !state.verified_at && (
          <StatusBanner tone="error" message={t("revokedByAdmin", { date: formatDate(state.revoked_at) })} />
        )}
        {state.verified_at && !state.show_identity && <StatusBanner tone="neutral" message={t("verifiedButHidden")} />}
        {rejected && <StatusBanner tone="error" message={t("rejected", { reason: state.request?.decision_note ?? "" })} />}
        {pending && state.request && (
          <p className="docverify-request">
            {t("pendingSince", { date: formatDate(state.request.requested_at), name: state.request.tenant_name })}
          </p>
        )}
        {!state.verified_at && !pending && (
          <label className="field-stack">
            <span className="field-label">{t("requestMessage")}</span>
            <textarea rows={3} maxLength={2000} value={message} placeholder={t("requestMessagePlaceholder")} onChange={(event) => setMessage(event.target.value)} />
          </label>
        )}
        <div className="docverify-actions-row">
          {pending ? (
            <button type="button" className="button-secondary" disabled={busy} onClick={() => void withdraw()}>{t("withdraw")}</button>
          ) : !state.verified_at ? (
            <button type="button" className="button-primary" disabled={busy} onClick={() => void requestVerification()}>{t("request")}</button>
          ) : null}
        </div>
      </section>

      <section className="panel docverify-section">
        <h3 className="docverify-heading">{t("previewTitle")}</h3>
        <p className="muted docverify-hint">{t("previewHint")}</p>
        <div className="docverify-preview" aria-label={t("previewTitle")}>
          <div className="docverify-preview-title">
            <span className="docverify-preview-icon" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
            </span>
            {t("previewOriginal")}
          </div>
          <p>{t("previewText", { date: formatDate(new Date().toISOString()) })}</p>
          {state.show_identity && (
            <div className="docverify-preview-identity">
              {state.has_logo ? (
                <img className="docverify-preview-logo" src={`/api/tenants/${state.tenant_id}/profile-image`} alt="" />
              ) : (
                <span className="docverify-preview-logo docverify-preview-initial" aria-hidden="true">{state.tenant_name.slice(0, 1).toUpperCase()}</span>
              )}
              <div>
                <strong>{state.tenant_name}</strong>
                <div className="docverify-preview-sub">
                  {state.verified_at ? <Badge variant="success">{t("previewBadge")}</Badge> : t("previewCreatedBy", { name: state.tenant_name })}
                </div>
                {domainInUse && (
                  <div className="docverify-preview-sub">
                    <Badge variant="info">{t("previewDomainBadge", { domain: domainInUse })}</Badge>
                  </div>
                )}
              </div>
            </div>
          )}
          {state.show_newer_version && <p className="docverify-preview-notice">{t("previewNewer")}</p>}
        </div>
      </section>
    </div>
  );
}
