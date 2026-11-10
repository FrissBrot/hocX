"use client";

import { useTranslations } from "next-intl";

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
  labelPlaceholder,
  code,
  onCodeChange,
  onSubmit,
  onCancel,
  busy = false,
  submitLabel,
  submitBusyLabel,
}: Props) {
  const t = useTranslations("security.totpEnroll");
  return (
    <div className="grid">
      <div className="wizard-dns-block">
        <span className="wizard-dns-label">{t("scanStep")}</span>
        <div className="totp-qr-row">
          <TotpQrCode value={setup.provisioning_uri} />
          <div className="totp-qr-hint">
            <p className="muted">
              {t("scanHint")}
            </p>
            <details className="totp-manual-entry">
              <summary>{t("manualEntrySummary")}</summary>
              <div className="totp-manual-entry-body">
                <CopyField label={t("setupKeyLabel")} value={setup.manual_entry_key} />
              </div>
            </details>
          </div>
        </div>
      </div>

      <div className="wizard-dns-block">
        <span className="wizard-dns-label">{t("confirmStep")}</span>
        <label className="field-stack">
          <span className="field-label">{t("designationLabel")}</span>
          <input value={label} onChange={(event) => onLabelChange(event.target.value)} placeholder={labelPlaceholder ?? t("designationPlaceholder")} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("codeLabel")}</span>
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
        <button type="button" className="button-secondary" disabled={code.length !== 6 || busy} onClick={onSubmit}>
          {busy ? (submitBusyLabel ?? t("submitBusy")) : (submitLabel ?? t("submit"))}
        </button>
        {onCancel ? (
          <button type="button" className="button-secondary button-ghost" onClick={onCancel}>
            {t("cancel")}
          </button>
        ) : null}
      </div>
    </div>
  );
}
