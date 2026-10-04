"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { CopyField } from "@/components/ui/copy-field";
import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { TenantDomain, TenantDomainPurpose } from "@/types/api";

type Props = {
  open: boolean;
  onClose: () => void;
  tenantId: string;
  /** Pending domain to resume verification for, or null to start a fresh "add domain" flow. */
  domain: TenantDomain | null;
  onChanged: () => void;
};

type Step = "purpose" | "dns" | "success";

function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M3 8.5 6.2 11.5 13 4" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

export function DomainWizardModal({ open, onClose, tenantId, domain, onChanged }: Props) {
  const t = useTranslations("tenantSettings");
  const tCommon = useTranslations("common");
  const showToast = useToast();
  const confirm = useConfirm();
  const [step, setStep] = useState<Step>("purpose");
  const [purpose, setPurpose] = useState<TenantDomainPurpose>("app");
  const [domainInput, setDomainInput] = useState("");
  const [activeDomain, setActiveDomain] = useState<TenantDomain | null>(null);
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const STEPS: { key: Step; label: string }[] = [
    { key: "purpose", label: t("stepDomain") },
    { key: "dns", label: t("stepDns") },
    { key: "success", label: t("stepDone") },
  ];

  useEffect(() => {
    if (!open) return;
    setErrorMsg(null);
    if (domain) {
      setActiveDomain(domain);
      setPurpose(domain.purpose);
      setStep(domain.status === "active" ? "success" : "dns");
    } else {
      setActiveDomain(null);
      setPurpose("app");
      setDomainInput("");
      setStep("purpose");
    }
  }, [open, domain]);

  async function createDomain() {
    if (!domainInput.trim()) return;
    setBusy(true);
    setErrorMsg(null);
    try {
      const created = await browserApiFetch<TenantDomain>(`/api/tenants/${tenantId}/domains`, {
        method: "POST",
        body: JSON.stringify({ purpose, domain: domainInput.trim() })
      });
      setActiveDomain(created);
      onChanged();
      setStep("dns");
    } catch (error) {
      setErrorMsg(error instanceof Error ? error.message : t("addDomainFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    if (!activeDomain) return;
    setBusy(true);
    setErrorMsg(null);
    try {
      const verified = await browserApiFetch<TenantDomain>(`/api/tenants/${tenantId}/domains/${activeDomain.id}/verify`, {
        method: "POST"
      });
      setActiveDomain(verified);
      onChanged();
      setStep("success");
    } catch (error) {
      setErrorMsg(error instanceof Error ? error.message : t("verifyFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function removeAndClose() {
    if (!activeDomain) return;
    // Was the only delete flow in the app without a confirmation dialog (audit F4,
    // 2026-08-16) - a misclick here during DNS setup instantly discarded the domain
    // config (incl. its verification token) with no way back.
    const ok = await confirm({
      message: t("removeDomainConfirm", { domain: activeDomain.domain }),
      tone: "danger",
      confirmLabel: tCommon("delete"),
    });
    if (!ok) return;
    setBusy(true);
    try {
      await browserApiFetch<{ message: string }>(`/api/tenants/${tenantId}/domains/${activeDomain.id}`, { method: "DELETE" });
      onChanged();
      onClose();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteDomainFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  function finish() {
    onChanged();
    onClose();
  }

  const stepIndex = STEPS.findIndex((s) => s.key === step);

  return (
    <Modal open={open} onClose={onClose} title={t("wizardTitle")} description={t("wizardDescription")}>
      <div className="wizard-steps">
        {STEPS.map((s, index) => (
          <div className="wizard-step" key={s.key} style={index === STEPS.length - 1 ? { flex: "0 0 auto" } : { flex: 1 }}>
            <div className={`wizard-step-dot${index === stepIndex ? " is-active" : ""}${index < stepIndex ? " is-done" : ""}`}>
              {index < stepIndex ? <CheckIcon /> : index + 1}
            </div>
            <span className={`wizard-step-label${index === stepIndex ? " is-active" : ""}`}>{s.label}</span>
            {index < STEPS.length - 1 && <div className={`wizard-step-line${index < stepIndex ? " is-done" : ""}`} />}
          </div>
        ))}
      </div>

      {errorMsg && <div className="form-error-banner">{errorMsg}</div>}

      {step === "purpose" && (
        <>
          <div className="wizard-purpose-grid">
            <button type="button" className={`wizard-purpose-card${purpose === "app" ? " is-selected" : ""}`} onClick={() => setPurpose("app")}>
              <span className="wizard-purpose-title">{t("purposeApp")}</span>
              <span className="wizard-purpose-desc">{t("wizardPurposeAppDescription")}</span>
            </button>
            <button type="button" className={`wizard-purpose-card${purpose === "abgabebox" ? " is-selected" : ""}`} onClick={() => setPurpose("abgabebox")}>
              <span className="wizard-purpose-title">{t("purposeAbgabebox")}</span>
              <span className="wizard-purpose-desc">{t("wizardPurposeAbgabeboxDescription")}</span>
            </button>
          </div>
          <label className="field-stack">
            <span className="field-label">{t("domainLabel")}</span>
            <input
              className="input"
              value={domainInput}
              onChange={(event) => setDomainInput(event.target.value.toLowerCase())}
              placeholder={t("domainPlaceholder")}
              autoFocus
            />
          </label>
          <div className="wizard-footer">
            <span />
            <div className="wizard-footer-actions">
              <button type="button" className="button-ghost" onClick={onClose}>{tCommon("cancel")}</button>
              <button type="button" className="button-primary" disabled={busy || !domainInput.trim()} onClick={createDomain}>
                {busy ? "…" : t("continueLabel")}
              </button>
            </div>
          </div>
        </>
      )}

      {step === "dns" && activeDomain && (
        <>
          <p className="muted">
            {t("dnsIntro", { domain: activeDomain.domain })}
          </p>

          <div className="wizard-dns-block">
            <span className="wizard-dns-label">{t("dnsStep1")}</span>
            <span className="wizard-dns-sublabel">{t("nameLabel")}</span>
            <CopyField label={t("txtNameLabel")} value={activeDomain.challenge_record_name} />
            <span className="wizard-dns-sublabel">{t("valueLabel")}</span>
            <CopyField label={t("txtValueLabel")} value={activeDomain.verification_token} />
          </div>

          {activeDomain.target_host && (
            <div className="wizard-dns-block">
              <span className="wizard-dns-label">{t("dnsStep2")}</span>
              <span className="wizard-dns-sublabel">{t("nameLabel")}</span>
              <CopyField label={t("cnameNameLabel")} value={activeDomain.domain} />
              <span className="wizard-dns-sublabel">{t("targetLabel")}</span>
              <CopyField label={t("targetHostLabel")} value={activeDomain.target_host} />
            </div>
          )}

          <div className="wizard-footer">
            <button type="button" className="button-ghost wizard-remove-link" disabled={busy} onClick={removeAndClose}>
              {t("deleteDomainLink")}
            </button>
            <div className="wizard-footer-actions">
              <button type="button" className="button-ghost" onClick={onClose}>{t("finishLater")}</button>
              <button type="button" className="button-primary" disabled={busy} onClick={verify}>
                {busy ? t("verifying") : t("verifyNow")}
              </button>
            </div>
          </div>
        </>
      )}

      {step === "success" && activeDomain && (
        <>
          <div className="wizard-success">
            <div className="wizard-success-icon">
              <CheckIcon />
            </div>
            <div>
              {t("successActive", { domain: activeDomain.domain })}
              <p className="muted" style={{ marginTop: "var(--space-1)" }}>
                {activeDomain.purpose === "app"
                  ? t("successAppDescription")
                  : t("successAbgabeboxDescription")}
              </p>
            </div>
          </div>
          <div className="wizard-footer">
            <span />
            <div className="wizard-footer-actions">
              <button type="button" className="button-primary" onClick={finish}>{t("finish")}</button>
            </div>
          </div>
        </>
      )}
    </Modal>
  );
}
