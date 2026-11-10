"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { TotpEnrollCard } from "@/components/security/totp-enroll-card";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { useMfaEnrollment, formatMfaDate, mfaFactorTypeLabel } from "@/lib/hooks/use-mfa-enrollment";
import { browserSupportsPasskeys } from "@/lib/webauthn";
import type { Locale } from "@/i18n/locale-config.generated";
import { UserMfaOverview } from "@/types/api";

type Props = {
  open: boolean;
};

export function MfaProfilePanel({ open }: Props) {
  const t = useTranslations("security.mfaProfile");
  const locale = useLocale() as Locale;
  const showToast = useToast();
  const [overview, setOverview] = useState<UserMfaOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const {
    totpSetup,
    setTotpSetup,
    totpCode,
    setTotpCode,
    totpLabel,
    setTotpLabel,
    passkeyLabel,
    setPasskeyLabel,
    busy,
    setBusy,
    startTotp,
    completeTotp,
    startPasskey,
    deleteFactor,
    hasTotpFactor,
    hasPasskeyFactor,
  } = useMfaEnrollment("/api/users/me/mfa", overview, setOverview);

  useEffect(() => {
    if (!open) {
      return;
    }
    setLoading(true);
    browserApiFetch<UserMfaOverview>("/api/users/me/mfa")
      .then((result) => setOverview(result))
      .catch((error) => {
        showToast(error instanceof Error ? error.message : t("loadFailed"), "error");
      })
      .finally(() => setLoading(false));
  }, [open, showToast, t]);

  async function setPreferredMethod(factorType: "totp" | "webauthn") {
    setBusy(true);
    try {
      const next = await browserApiFetch<UserMfaOverview>("/api/users/me/mfa/preferred-method", {
        method: "PATCH",
        body: JSON.stringify({ factor_type: factorType }),
      });
      setOverview(next);
      showToast(t("setDefaultSuccess", { method: mfaFactorTypeLabel(factorType) }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("setDefaultFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid">
      <div className="security-summary-card">
        <div>
          <div className="eyebrow">{t("statusEyebrow")}</div>
          <strong>
            {loading
              ? t("loading")
              : overview?.required
                ? t("requiredStatus")
                : overview?.has_factors
                  ? t("activeStatus")
                  : t("optionalStatus")}
          </strong>
          <div className="muted">
            {overview?.required
              ? t("requiredHint")
              : t("optionalHint")}
          </div>
          {overview?.preferred_factor_label ? (
            <div className="muted">{t("defaultMethod", { method: overview.preferred_factor_label })}</div>
          ) : null}
        </div>
        <div className="status-row">
          <span className="pill">{t("factorCount", { count: overview?.factors.length ?? 0 })}</span>
          {overview?.preferred_factor_type ? <span className="pill">{t("defaultPill", { method: mfaFactorTypeLabel(overview.preferred_factor_type) })}</span> : null}
          <span className="pill">{browserSupportsPasskeys() ? t("passkeysAvailable") : t("passkeysUnavailable")}</span>
        </div>
      </div>

      <div className="wizard-steps">
        <div className="wizard-step">
          <div className="wizard-step-dot is-done">1</div>
          <div className="wizard-step-label is-active">{t("stepChooseMethod")}</div>
        </div>
        <div className="wizard-step-line is-done" />
        <div className="wizard-step">
          <div className={`wizard-step-dot${totpSetup ? " is-active" : overview?.has_factors ? " is-done" : ""}`}>2</div>
          <div className={`wizard-step-label${totpSetup ? " is-active" : ""}`}>{t("stepConfirm")}</div>
        </div>
        <div className="wizard-step-line" />
        <div className="wizard-step">
          <div className={`wizard-step-dot${overview?.has_factors ? " is-done" : ""}`}>3</div>
          <div className="wizard-step-label">{t("stepDone")}</div>
        </div>
      </div>

      <div className="two-col">
        <article className="security-method-card">
          <div className="security-method-header">
            <div>
              <div className="eyebrow">{t("optionA")}</div>
              <h3>{t("totpTitle")}</h3>
            </div>
            {overview?.preferred_factor_type === "totp" ? (
              <span className="pill">{t("loginDefaultPill")}</span>
            ) : (
              <span className="pill">{t("universalPill")}</span>
            )}
          </div>
          <p className="muted">
            {t("totpDescription")}
          </p>
          {hasTotpFactor && overview?.preferred_factor_type !== "totp" ? (
            <button type="button" className="button-secondary button-ghost" disabled={busy} onClick={() => void setPreferredMethod("totp")}>
              {t("setAsDefault")}
            </button>
          ) : null}
          {!totpSetup ? (
            <button type="button" className="button-secondary" onClick={() => void startTotp()}>
              {t("setUpTotp")}
            </button>
          ) : (
            <TotpEnrollCard
              setup={totpSetup}
              label={totpLabel}
              onLabelChange={setTotpLabel}
              code={totpCode}
              onCodeChange={setTotpCode}
              onSubmit={() => void completeTotp()}
              onCancel={() => setTotpSetup(null)}
              busy={busy}
            />
          )}
        </article>

        <article className="security-method-card">
          <div className="security-method-header">
            <div>
              <div className="eyebrow">{t("optionB")}</div>
              <h3>{t("passkeyTitle")}</h3>
            </div>
            {overview?.preferred_factor_type === "webauthn" ? (
              <span className="pill">{t("loginDefaultPill")}</span>
            ) : (
              <span className="pill">{t("comfortablePill")}</span>
            )}
          </div>
          <p className="muted">
            {t("passkeyDescription")}
          </p>
          {hasPasskeyFactor && overview?.preferred_factor_type !== "webauthn" ? (
            <button
              type="button"
              className="button-secondary button-ghost"
              disabled={busy}
              onClick={() => void setPreferredMethod("webauthn")}
            >
              {t("setAsDefault")}
            </button>
          ) : null}
          {overview?.can_add_passkey_here ? (
            <div className="grid">
              <label className="field-stack">
                <span className="field-label">{t("designationLabel")}</span>
                <input
                  value={passkeyLabel}
                  onChange={(event) => setPasskeyLabel(event.target.value)}
                  placeholder={t("passkeyLabelPlaceholder")}
                />
              </label>
              <button type="button" className="button-secondary" disabled={busy} onClick={() => void startPasskey()}>
                {busy ? t("preparingPasskey") : t("addPasskey")}
              </button>
            </div>
          ) : (
            <div className="info-note">
              {t("passkeyMainDomainOnlyNote")}
            </div>
          )}
        </article>
      </div>

      <div className="grid">
        <div className="field-label">{t("activeFactorsLabel")}</div>
        <div className="security-factor-list">
          {!overview?.factors.length ? <div className="selection-card muted">{t("noFactorsYet")}</div> : null}
          {overview?.factors.map((factor) => {
            // The backend already rejects this with a 409 (delete_self_factor requires at
            // least one factor to remain when MFA is required), but the button here gave
            // no indication of that until the request failed (audit finding, 2026-08-25).
            const isLastRequiredFactor = Boolean(overview?.required) && (overview?.factors.length ?? 0) <= 1;
            return (
              <article key={factor.id} className="security-factor-card">
                <div className="security-factor-main">
                  <div className="security-factor-row">
                    <strong>{factor.label}</strong>
                    <span className="pill">{mfaFactorTypeLabel(factor.factor_type)}</span>
                  </div>
                  <div className="muted">{t("setUpAt", { date: formatMfaDate(factor.created_at, locale) })}</div>
                  <div className="muted">{t("lastUsedAt", { date: formatMfaDate(factor.last_used_at, locale) })}</div>
                  {isLastRequiredFactor && (
                    <div className="muted">{t("lastRequiredFactorNote")}</div>
                  )}
                </div>
                <button
                  type="button"
                  className="button-secondary button-danger"
                  disabled={isLastRequiredFactor}
                  title={isLastRequiredFactor ? t("lastRequiredFactorTitle") : undefined}
                  onClick={() => void deleteFactor(factor.id, factor.label)}
                >
                  {t("remove")}
                </button>
              </article>
            );
          })}
        </div>
      </div>
    </div>
  );
}
