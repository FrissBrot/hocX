"use client";

import { CopyField } from "@/components/ui/copy-field";
import { TotpQrCode } from "@/components/security/totp-qr-code";
import { TotpEnrollmentStart } from "@/types/api";

function sanitizeTotpCode(value: string) {
  return value.replace(/\D/g, "").slice(0, 6);
}

type Props = {
  setup: TotpEnrollmentStart;
  label: string;
  onLabelChange: (value: string) => void;
  labelPlaceholder?: string;
  code: string;
  onCodeChange: (value: string) => void;
  onSubmit: () => void;
  onCancel?: () => void;
  busy?: boolean;
  submitLabel?: string;
  submitBusyLabel?: string;
};

/**
 * Shared "scan → confirm" body for TOTP enrolment, styled after the domain
 * verification wizard's numbered DNS blocks (see DomainWizardModal).
 */
export function TotpEnrollCard({
  setup,
  label,
  onLabelChange,
  labelPlaceholder = "z.B. Diensthandy",
  code,
  onCodeChange,
  onSubmit,
  onCancel,
  busy = false,
  submitLabel = "TOTP aktivieren",
  submitBusyLabel = "Wird bestätigt…",
}: Props) {
  return (
    <div className="grid">
      <div className="wizard-dns-block">
        <span className="wizard-dns-label">1. QR-Code scannen</span>
        <div className="totp-qr-row">
          <TotpQrCode value={setup.provisioning_uri} />
          <div className="totp-qr-hint">
            <p className="muted">
              Code mit einer Authenticator-App scannen, z.B. Bitwarden, 1Password oder Google Authenticator.
            </p>
            <details className="totp-manual-entry">
              <summary>Kein Scanner zur Hand? Setup-Key manuell eingeben</summary>
              <div className="totp-manual-entry-body">
                <CopyField label="Setup-Key" value={setup.manual_entry_key} />
              </div>
            </details>
          </div>
        </div>
      </div>

      <div className="wizard-dns-block">
        <span className="wizard-dns-label">2. Code bestätigen</span>
        <label className="field-stack">
          <span className="field-label">Bezeichnung</span>
          <input value={label} onChange={(event) => onLabelChange(event.target.value)} placeholder={labelPlaceholder} />
        </label>
        <label className="field-stack">
          <span className="field-label">6-stelliger Code aus der App</span>
          <input
            value={code}
            onChange={(event) => onCodeChange(sanitizeTotpCode(event.target.value))}
            inputMode="numeric"
            placeholder="123456"
            autoComplete="one-time-code"
          />
        </label>
      </div>

      <div className="table-actions table-actions-start">
        <button type="button" className="button-inline" disabled={code.length !== 6 || busy} onClick={onSubmit}>
          {busy ? submitBusyLabel : submitLabel}
        </button>
        {onCancel ? (
          <button type="button" className="button-inline button-ghost" onClick={onCancel}>
            Abbrechen
          </button>
        ) : null}
      </div>
    </div>
  );
}
