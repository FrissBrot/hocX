"use client";

import Link from "next/link";
import { ReactNode, useState } from "react";
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
  const domainStatus = verifyDomainStatus(state, t);
  const domainInUse = state.verify_domain?.in_use ? state.verify_domain.domain : null;
  const domainDone = domainStatus.variant === "success";
  const verified = Boolean(state.verified_at);
  const previewHost = domainInUse ?? hostOf(state.verify_base_url);
  const domainLink = state.verify_domain || state.has_verify_domain_feature;

  return (
    <div className="docverify">
      <div className="grid docverify-main">
        <p className="muted docverify-intro">{t("intro")}</p>

        <section className="card docverify-card">
          <div className="docverify-card-head">
            <h2 className="docverify-heading">{t("publicTitle")}</h2>
            <a className="docverify-link" href={state.verify_base_url} target="_blank" rel="noopener noreferrer">
              {t("openPage")}
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M7 17L17 7M9 7h8v8" /></svg>
            </a>
          </div>
          {(
            [
              ["show_identity", t("showIdentity"), t("showIdentityHint")],
              ["show_newer_version", t("showNewerVersion"), t("showNewerVersionHint")],
            ] as const
          ).map(([key, label, hint]) => (
            <label key={key} className="docverify-toggle">
              <input type="checkbox" role="switch" disabled={busy} checked={state[key]} onChange={(event) => void toggle(key, event.target.checked)} />
              <span className="album-picker-switch-track" aria-hidden="true" />
              <span className="docverify-toggle-text">
                <span className="docverify-toggle-label">{label}</span>
                <span className="docverify-toggle-hint">{hint}</span>
              </span>
            </label>
          ))}
        </section>

        <section className="card docverify-card">
          <div className="docverify-levels-head">
            <h2 className="docverify-heading">{t("levelsTitle")}</h2>
            <span className="docverify-toggle-hint">{t("levelsIntro")}</span>
          </div>

          <Level done mark="1" title={t("levelAuthenticity")} pill={<Badge variant="success">{t("alwaysActive")}</Badge>}>
            <span>{t("levelAuthenticityText")}</span>
          </Level>

          <Level
            done={domainDone}
            mark="2"
            title={t("domainTitle")}
            pill={<Badge variant={state.verify_domain ? domainStatus.variant : "neutral"}>{state.verify_domain ? domainStatus.label : state.has_verify_domain_feature ? t("domainStatusNotSetUp") : t("domainStatusNotBooked")}</Badge>}
          >
            <span>{t("levelDomainText")}</span>
            {state.verify_domain || domainLink ? (
              <div className="docverify-domain-row">
                {state.verify_domain ? <code className="docverify-domain">{state.verify_domain.domain}</code> : <span />}
                {domainLink ? (
                  <Link className="docverify-link" href="/tenant-settings/domains">
                    {state.verify_domain ? t("domainManage") : t("domainSetup")} →
                  </Link>
                ) : null}
              </div>
            ) : null}
            {domainStatus.hint ? <span className="docverify-note">{domainStatus.hint}</span> : null}
            {!state.verify_domain && !state.has_verify_domain_feature ? <span className="docverify-note">{t("domainNotBooked")}</span> : null}
          </Level>

          <Level
            done={verified}
            mark="3"
            title={t("verificationTitle")}
            pill={
              verified ? (
                <Badge variant="success">{t("verifiedSince", { date: formatDate(state.verified_at) })}</Badge>
              ) : pending ? (
                <Badge variant="info">{t("pending")}</Badge>
              ) : (
                <Badge variant="neutral">{t("notVerified")}</Badge>
              )
            }
          >
            <span>{t("levelVerificationText")}</span>
            {verified ? <span className="docverify-note">{state.show_identity ? t("verifiedNameChangeNote") : t("verifiedButHidden")}</span> : null}
            {state.revoked_reason === "name_changed" && !verified ? (
              <StatusBanner tone="error" message={t("revokedNameChanged", { date: formatDate(state.revoked_at) })} />
            ) : null}
            {state.revoked_reason === "admin" && !verified ? <StatusBanner tone="error" message={t("revokedByAdmin", { date: formatDate(state.revoked_at) })} /> : null}
            {rejected ? <StatusBanner tone="error" message={t("rejected", { reason: state.request?.decision_note ?? "" })} /> : null}
            {pending && state.request ? (
              <span>{t("pendingSince", { date: formatDate(state.request.requested_at), name: state.request.tenant_name })}</span>
            ) : null}
            {!verified && !pending ? (
              <label className="field-stack docverify-request">
                <span className="field-label">{t("requestMessage")}</span>
                <textarea rows={3} maxLength={2000} value={message} placeholder={t("requestMessagePlaceholder")} onChange={(event) => setMessage(event.target.value)} />
              </label>
            ) : null}
            {pending ? (
              <div className="docverify-actions-row">
                <button type="button" className="button-secondary" disabled={busy} onClick={() => void withdraw()}>{t("withdraw")}</button>
              </div>
            ) : !verified ? (
              <div className="docverify-actions-row">
                <button type="button" className="button-primary" disabled={busy} onClick={() => void requestVerification()}>{t("request")}</button>
              </div>
            ) : null}
          </Level>
        </section>
      </div>

      <aside className="docverify-side" aria-label={t("previewTitle")}>
        <div className="docverify-side-head">
          <span className="docverify-eyebrow">{t("previewTitle")}</span>
          <span className="muted docverify-side-example">{t("previewExample")}</span>
        </div>
        <div className="docverify-frame">
          <div className="docverify-window">
            <div className="docverify-url">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M6 10.5h12v10H6zM8.5 10.5V7.5a3.5 3.5 0 017 0v3" /></svg>
              {previewHost}/{PREVIEW_ID}
            </div>
            <div className="docverify-window-body">
              <div className="docverify-result">
                <span className="docverify-result-icon" aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
                </span>
                <div>
                  <div className="docverify-result-title">{t("previewOriginal")}</div>
                  <div className="docverify-result-text">{t("previewText", { date: formatDate(new Date().toISOString()) })}</div>
                </div>
              </div>
              {state.show_identity ? (
                <div className="docverify-issuer">
                  {state.has_logo ? (
                    <img className="docverify-issuer-logo" src={`/api/tenants/${state.tenant_id}/profile-image`} alt="" />
                  ) : (
                    <span className="docverify-issuer-logo docverify-issuer-initials" aria-hidden="true">{initialsOf(state.tenant_name)}</span>
                  )}
                  <div className="docverify-issuer-text">
                    <span className="docverify-eyebrow">{t("previewIssuedBy")}</span>
                    <strong>{state.tenant_name}</strong>
                    {verified || domainInUse ? (
                      <div className="docverify-badges">
                        {verified ? <Badge variant="success">✓ {t("previewBadge")}</Badge> : null}
                        {domainInUse ? <Badge variant="info">{t("previewDomainLevel")}</Badge> : null}
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : (
                <div className="docverify-issuer-hidden">{t("previewHidden")}</div>
              )}
              <dl className="docverify-meta">
                <div><dt>{t("previewType")}</dt><dd>{t("previewTypeValue")}</dd></div>
                <div><dt>{t("previewVersion")}</dt><dd>v1.2</dd></div>
                <div><dt>{t("previewId")}</dt><dd className="docverify-mono">{PREVIEW_ID}</dd></div>
              </dl>
              {state.show_newer_version ? (
                <div className="docverify-newer">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M20.5 12a8.5 8.5 0 11-17 0 8.5 8.5 0 0117 0zM12 11v5M12 8h.01" /></svg>
                  <span>{t("previewNewer")}</span>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}

const PREVIEW_ID = "249A-0313";

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

/** Eine Vertrauensstufe: erledigt (Häkchen) oder offen (Nummer). */
function Level({ done, mark, title, pill, children }: { done: boolean; mark: string; title: string; pill: ReactNode; children: ReactNode }) {
  return (
    <div className={`docverify-level${done ? " docverify-level-done" : ""}`}>
      <span className="docverify-level-mark" aria-hidden="true">{done ? "✓" : mark}</span>
      <div className="docverify-level-body">
        <div className="docverify-level-head">
          <span className="docverify-level-title">{title}</span>
          {pill}
        </div>
        {children}
      </div>
    </div>
  );
}
