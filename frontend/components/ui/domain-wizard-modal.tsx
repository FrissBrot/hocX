"use client";

import { useEffect, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { TenantDomain, TenantDomainPurpose } from "@/types/api";

type Props = {
  open: boolean;
  onClose: () => void;
  tenantId: number;
  /** Pending domain to resume verification for, or null to start a fresh "add domain" flow. */
  domain: TenantDomain | null;
  onChanged: () => void;
};

type Step = "purpose" | "dns" | "success";

const STEPS: { key: Step; label: string }[] = [
  { key: "purpose", label: "Domain" },
  { key: "dns", label: "DNS einrichten" },
  { key: "success", label: "Fertig" },
];

function CopyIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.4" />
      <path d="M3.5 10.5h-1a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h7a1 1 0 0 1 1 1v1" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M3 8.5 6.2 11.5 13 4" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard-Zugriff kann in manchen Browsern/Kontexten fehlschlagen - kein Beinbruch,
      // der Wert steht trotzdem sichtbar da und kann markiert werden.
    }
  }

  return (
    <div className="wizard-dns-row">
      <div className="wizard-dns-value">{value}</div>
      <button type="button" className={`wizard-copy-button${copied ? " is-copied" : ""}`} onClick={copy} aria-label={`${label} kopieren`} title="Kopieren">
        {copied ? <CheckIcon /> : <CopyIcon />}
      </button>
    </div>
  );
}

export function DomainWizardModal({ open, onClose, tenantId, domain, onChanged }: Props) {
  const showToast = useToast();
  const [step, setStep] = useState<Step>("purpose");
  const [purpose, setPurpose] = useState<TenantDomainPurpose>("app");
  const [domainInput, setDomainInput] = useState("");
  const [activeDomain, setActiveDomain] = useState<TenantDomain | null>(null);
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

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
      setErrorMsg(error instanceof Error ? error.message : "Domain konnte nicht hinzugefügt werden");
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
      setErrorMsg(error instanceof Error ? error.message : "Verifizierung fehlgeschlagen");
    } finally {
      setBusy(false);
    }
  }

  async function removeAndClose() {
    if (!activeDomain) return;
    setBusy(true);
    try {
      await browserApiFetch<{ message: string }>(`/api/tenants/${tenantId}/domains/${activeDomain.id}`, { method: "DELETE" });
      onChanged();
      onClose();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Domain konnte nicht entfernt werden", "error");
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
    <Modal open={open} onClose={onClose} title="Custom Domain einrichten" description="In drei Schritten eine eigene Domain für diesen Mandanten verbinden.">
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
              <span className="wizard-purpose-title">hocX-App</span>
              <span className="wizard-purpose-desc">Die normale hocX-Oberfläche unter der eigenen Domain aufrufen.</span>
            </button>
            <button type="button" className={`wizard-purpose-card${purpose === "abgabebox" ? " is-selected" : ""}`} onClick={() => setPurpose("abgabebox")}>
              <span className="wizard-purpose-title">Abgabebox</span>
              <span className="wizard-purpose-desc">Die öffentliche Abgabebox unter der eigenen Domain erreichbar machen.</span>
            </button>
          </div>
          <label className="field-stack">
            <span className="field-label">Domain</span>
            <input
              className="input"
              value={domainInput}
              onChange={(event) => setDomainInput(event.target.value.toLowerCase())}
              placeholder="z.B. verein.example.ch"
              autoFocus
            />
          </label>
          <div className="wizard-footer">
            <span />
            <div className="wizard-footer-actions">
              <button type="button" className="button-ghost" onClick={onClose}>Abbrechen</button>
              <button type="button" className="button-primary" disabled={busy || !domainInput.trim()} onClick={createDomain}>
                {busy ? "…" : "Weiter"}
              </button>
            </div>
          </div>
        </>
      )}

      {step === "dns" && activeDomain && (
        <>
          <p className="muted">
            Bei deinem Domain-Provider zwei Einträge für <strong>{activeDomain.domain}</strong> setzen, dann verifizieren.
            {" "}hocx.tweber.ch bzw. die Standard-Abgabebox-Domain bleiben zusätzlich immer erreichbar.
          </p>

          <div className="wizard-dns-block">
            <span className="wizard-dns-label">1. Besitznachweis · TXT-Record</span>
            <span className="wizard-dns-sublabel">Name</span>
            <CopyField label="TXT-Name" value={activeDomain.challenge_record_name} />
            <span className="wizard-dns-sublabel">Wert</span>
            <CopyField label="TXT-Wert" value={activeDomain.verification_token} />
          </div>

          {activeDomain.target_host && (
            <div className="wizard-dns-block">
              <span className="wizard-dns-label">2. Routing · CNAME/A-Record</span>
              <span className="wizard-dns-sublabel">Name</span>
              <CopyField label="CNAME/A-Name" value={activeDomain.domain} />
              <span className="wizard-dns-sublabel">Ziel</span>
              <CopyField label="Ziel-Host" value={activeDomain.target_host} />
            </div>
          )}

          <div className="wizard-footer">
            <button type="button" className="button-ghost wizard-remove-link" disabled={busy} onClick={removeAndClose}>
              Domain entfernen
            </button>
            <div className="wizard-footer-actions">
              <button type="button" className="button-ghost" onClick={onClose}>Später fertigstellen</button>
              <button type="button" className="button-primary" disabled={busy} onClick={verify}>
                {busy ? "Wird geprüft…" : "Jetzt verifizieren"}
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
              <strong>{activeDomain.domain}</strong> ist aktiv.
              <p className="muted" style={{ marginTop: "4px" }}>
                {activeDomain.purpose === "app"
                  ? "Die hocX-App ist ab sofort auch unter dieser Domain erreichbar."
                  : "Die Abgabebox ist ab sofort auch unter dieser Domain erreichbar."}
              </p>
            </div>
          </div>
          <div className="wizard-footer">
            <span />
            <div className="wizard-footer-actions">
              <button type="button" className="button-primary" onClick={finish}>Fertig</button>
            </div>
          </div>
        </>
      )}
    </Modal>
  );
}
