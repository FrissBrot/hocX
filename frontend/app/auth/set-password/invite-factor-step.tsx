"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { StatusBanner } from "@/components/ui/status-banner";
import { CopyField } from "@/components/ui/copy-field";
import { TotpQrCode } from "@/components/security/totp-qr-code";
import { TOTP_CODE_LENGTH, TotpCodeInputs } from "@/components/security/totp-code-inputs";
import { useConfirm } from "@/contexts/confirm-context";
import { browserApiFetch } from "@/lib/api/client";
import { apiErrorCode, apiErrorMessage } from "@/lib/api/error-message";
import { createPasskeyCredential } from "@/lib/webauthn";
import type { LoginResponse, PasskeyRegistrationStart, PendingMfaLogin, TotpEnrollmentStart } from "@/types/api";

export type FactorResult = { session: LoginResponse; factor: "webauthn" | "totp" | null; label: string };

type Props = {
  pending: PendingMfaLogin;
  tenantName: string;
  passkeysSupported: boolean;
  onDone: (result: FactorResult) => void;
  onExpired: () => void;
};

/** Schlüssel in Vierergruppen, wie ihn Authenticator-Apps bei der manuellen Eingabe zeigen. */
function groupKey(key: string): string {
  return key.replace(/\s+/g, "").replace(/(.{4})(?=.)/g, "$1 ");
}

/**
 * Schritt «Zweiten Faktor einrichten» des Erstlogins über eine Einladung. Läuft über das Login-
 * Ticket aus /api/auth/account-link/complete und die bestehenden Login-Endpunkte für die
 * Ersteinrichtung; erst der bestätigte Faktor (bzw. das erlaubte Überspringen) setzt die Session.
 */
export function InviteFactorStep({ pending, tenantName, passkeysSupported, onDone, onExpired }: Props) {
  const t = useTranslations("auth.setPassword");
  const tAuth = useTranslations("auth");
  const tSecurity = useTranslations("security");
  const confirm = useConfirm();
  const passkeyAvailable = passkeysSupported && pending.can_add_passkey;
  const [method, setMethod] = useState<"webauthn" | "totp">(passkeyAvailable ? "webauthn" : "totp");
  const [view, setView] = useState<"choose" | "totp" | "webauthn">("choose");
  const [totpSetup, setTotpSetup] = useState<TotpEnrollmentStart | null>(null);
  const [code, setCode] = useState("");
  const [label, setLabel] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function handleError(caught: unknown, fallback: string) {
    const errorCode = apiErrorCode(caught);
    if (errorCode === "mfa_flow_expired" && !totpSetup) {
      onExpired();
      return;
    }
    if (errorCode === "rate_limited") {
      setError(t("rateLimited"));
      return;
    }
    setError(apiErrorMessage(caught, tSecurity, "apiErrors", fallback));
  }

  async function startTotp() {
    setBusy(true);
    setError("");
    try {
      const setup = await browserApiFetch<TotpEnrollmentStart>("/api/auth/mfa/totp/setup/start", {
        method: "POST",
        body: JSON.stringify({ ticket: pending.ticket }),
      });
      setTotpSetup(setup);
      setCode("");
      setView("totp");
    } catch (caught) {
      handleError(caught, tAuth("status.totpSetupStartFailed"));
    } finally {
      setBusy(false);
    }
  }

  function continueWithMethod() {
    setError("");
    if (method === "webauthn" && passkeyAvailable) {
      setView("webauthn");
      return;
    }
    if (totpSetup) {
      setView("totp");
      return;
    }
    void startTotp();
  }

  async function activateTotp() {
    if (!totpSetup || code.length !== TOTP_CODE_LENGTH) return;
    setBusy(true);
    setError("");
    try {
      const session = await browserApiFetch<LoginResponse>("/api/auth/mfa/totp/setup/complete", {
        method: "POST",
        body: JSON.stringify({ flow_token: totpSetup.flow_token, code, label: label.trim() || null }),
      });
      onDone({ session, factor: "totp", label: label.trim() });
    } catch (caught) {
      if (apiErrorCode(caught) === "mfa_flow_expired") {
        onExpired();
        return;
      }
      handleError(caught, tAuth("status.totpActivateFailed"));
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  async function runPasskey() {
    setBusy(true);
    setError("");
    try {
      const start = await browserApiFetch<PasskeyRegistrationStart>("/api/auth/mfa/passkeys/setup/start", {
        method: "POST",
        body: JSON.stringify({ ticket: pending.ticket }),
      });
      const credential = await createPasskeyCredential(start.public_key);
      const session = await browserApiFetch<LoginResponse>("/api/auth/mfa/passkeys/setup/complete", {
        method: "POST",
        body: JSON.stringify({ flow_token: start.flow_token, label: label.trim() || null, credential }),
      });
      onDone({ session, factor: "webauthn", label: label.trim() });
    } catch (caught) {
      if (apiErrorCode(caught) === "mfa_flow_expired") {
        onExpired();
        return;
      }
      handleError(caught, tAuth("status.passkeyFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function skip() {
    const confirmed = await confirm({
      title: t("skip.title"),
      message: t("skip.message"),
      confirmLabel: t("skip.confirm"),
      cancelLabel: t("skip.cancel"),
    });
    if (!confirmed) return;
    setBusy(true);
    setError("");
    try {
      const session = await browserApiFetch<LoginResponse>("/api/auth/mfa/setup/skip", {
        method: "POST",
        body: JSON.stringify({ ticket: pending.ticket }),
      });
      onDone({ session, factor: null, label: "" });
    } catch (caught) {
      handleError(caught, t("failed"));
    } finally {
      setBusy(false);
    }
  }

  function backToChoice() {
    setError("");
    setView("choose");
  }

  const errorBanner = error ? <StatusBanner tone="error" message={error} /> : null;

  if (view === "totp" && totpSetup) {
    return (
      <div className="invite-step">
        <div className="invite-step-heading">
          <h1>{t("totp.title")}</h1>
        </div>
        <section className="invite-block">
          <span className="invite-block-label">{t("totp.connectStep")}</span>
          <div className="invite-totp-connect">
            <div className="invite-totp-qr">
              <TotpQrCode value={totpSetup.provisioning_uri} size={160} />
            </div>
            <div className="invite-totp-text">
              <p className="muted invite-totp-qr-hint">{t("totp.qrHint")}</p>
              <p className="muted invite-totp-app-hint">{t("totp.openInAppHint")}</p>
              {/* otpauth-Link öffnet die App auf demselben Gerät; er verlässt das Gerät nicht (kein Server). */}
              <a className="button-secondary invite-totp-open" href={totpSetup.provisioning_uri}>{t("totp.openInApp")}</a>
              <button type="button" className="button-ghost invite-inline-toggle" onClick={() => setShowKey((current) => !current)} aria-expanded={showKey}>
                {showKey ? t("totp.hideKey") : t("totp.showKey")}
              </button>
              {showKey ? <CopyField label={t("totp.keyLabel")} value={groupKey(totpSetup.manual_entry_key)} /> : null}
            </div>
          </div>
        </section>
        <form
          className="invite-block"
          onSubmit={(event) => {
            event.preventDefault();
            void activateTotp();
          }}
        >
          <span className="invite-block-label">{t("totp.confirmStep")}</span>
          <div className="field-stack">
            <span className="field-label">{t("totp.codeLabel")}</span>
            <TotpCodeInputs code={code} onChange={setCode} digitLabel={(n) => tAuth("mfa.codeDigitLabel", { n })} disabled={busy} />
          </div>
          <label className="field-stack">
            <span className="field-label">{t("labelLabel")} <span className="invite-optional">{t("optional")}</span></span>
            <input className="input" value={label} onChange={(event) => setLabel(event.target.value)} placeholder={t("totp.labelPlaceholder")} maxLength={120} />
          </label>
          {errorBanner}
          <button type="submit" className="button-primary invite-submit" disabled={busy || code.length !== TOTP_CODE_LENGTH}>
            {busy ? t("totp.submitting") : t("totp.submit")}
          </button>
          <button type="button" className="button-ghost invite-back" onClick={backToChoice} disabled={busy}>{t("otherMethod")}</button>
        </form>
      </div>
    );
  }

  if (view === "webauthn") {
    return (
      <div className="invite-step">
        <div className="invite-step-heading">
          <h1>{t("passkey.title")}</h1>
          <p className="muted">{t("passkey.description")}</p>
        </div>
        <label className="field-stack">
          <span className="field-label">{t("labelLabel")} <span className="invite-optional">{t("optional")}</span></span>
          <input className="input" value={label} onChange={(event) => setLabel(event.target.value)} placeholder={t("passkey.labelPlaceholder")} maxLength={120} />
        </label>
        {errorBanner}
        <button type="button" className="button-primary invite-submit" onClick={() => void runPasskey()} disabled={busy}>
          {busy ? t("passkey.submitting") : t("passkey.submit")}
        </button>
        <button type="button" className="button-ghost invite-back" onClick={backToChoice} disabled={busy}>{t("otherMethod")}</button>
      </div>
    );
  }

  return (
    <div className="invite-step">
      <div className="invite-step-heading">
        <Badge variant="success" dot>{t("passwordSaved")}</Badge>
        <h1>{t("factor.title")}</h1>
        <p className="muted">{t("factor.intro")}</p>
      </div>
      {pending.required ? (
        <div className="invite-required">
          <strong>{t("factor.required", { tenant: tenantName })}</strong>
          <span>{t("factor.requiredDetail")}</span>
        </div>
      ) : null}
      <div className="invite-methods" role="radiogroup" aria-label={t("factor.title")}>
        <button
          type="button"
          role="radio"
          aria-checked={method === "webauthn" && passkeyAvailable}
          className={method === "webauthn" && passkeyAvailable ? "wizard-purpose-card is-selected" : "wizard-purpose-card"}
          onClick={() => setMethod("webauthn")}
          disabled={!passkeyAvailable}
        >
          <span className="wizard-purpose-title">
            {t("factor.passkeyTitle")}
            {passkeyAvailable ? <Badge variant="info">{t("factor.recommended")}</Badge> : null}
          </span>
          <span className="wizard-purpose-desc">{passkeyAvailable ? t("factor.passkeyAvailable") : t("factor.passkeyUnavailable")}</span>
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={method === "totp"}
          className={method === "totp" ? "wizard-purpose-card is-selected" : "wizard-purpose-card"}
          onClick={() => setMethod("totp")}
        >
          <span className="wizard-purpose-title">{t("factor.totpTitle")}</span>
          <span className="wizard-purpose-desc">{t("factor.totpDescription")}</span>
        </button>
      </div>
      {errorBanner}
      <button type="button" className="button-primary invite-submit" onClick={continueWithMethod} disabled={busy}>
        {busy ? t("totp.preparing") : t("factor.continue")}
      </button>
      {pending.can_skip && !pending.required ? (
        <button type="button" className="button-ghost invite-back" onClick={() => void skip()} disabled={busy}>{t("factor.later")}</button>
      ) : (
        <p className="muted invite-footnote">{t("factor.abortHint")}</p>
      )}
    </div>
  );
}
