"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { browserApiFetch } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/error-message";
import { browserSupportsPasskeys, createPasskeyCredential, getPasskeyAssertion } from "@/lib/webauthn";
import { AdminLoginResponse, AdminSessionInfo, PasskeyAssertionStart, PasskeyRegistrationStart, PendingMfaLogin } from "@/types/api";
import { CopyrightNotice } from "@/components/ui/copyright-notice";

// Plattform-Admins melden sich nur mit Passwort + Passkey an (kein TOTP, kein SSO). Ein Konto ohne
// Passkey richtet nach dem Passwort zwingend einen ein und bekommt erst danach eine Session
// (backend/app/services/admin_mfa_service.py).
export default function AdminLoginPage() {
  const t = useTranslations("admin.login");
  // Fehlercodes des Backends (invalid_credentials, passkey_invalid, rate_limited …) teilt sich der
  // Admin-Login mit dem Mandanten-Login
  const tSecurity = useTranslations("security");
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [statusMsg, setStatusMsg] = useState("");
  const [loading, setLoading] = useState(false);
  const [pendingMfa, setPendingMfa] = useState<PendingMfaLogin | null>(null);
  const [passkeyLabel, setPasskeyLabel] = useState("");
  const [passkeysSupported, setPasskeysSupported] = useState(true);

  useEffect(() => {
    setPasskeysSupported(browserSupportsPasskeys());
    async function checkSession() {
      try {
        const session = await browserApiFetch<AdminSessionInfo>("/api/admin/auth/session");
        if (session.authenticated) {
          router.replace("/admin");
        }
      } catch {}
    }
    void checkSession();
  }, [router]);

  function finishLogin() {
    // Nur replace(), kein zusätzliches refresh() - beide lösen sonst nahezu gleichzeitig
    // eine Server-Neuladen für die Zielroute aus (spürbar als Login-Loop).
    router.replace("/admin");
  }

  function resetMfaFlow() {
    setPendingMfa(null);
    setPasskeyLabel("");
    setStatusMsg("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setStatusMsg(t("status.loggingIn"));
    try {
      const result = await browserApiFetch<AdminLoginResponse>("/api/admin/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      if (result.authenticated) {
        finishLogin();
        return;
      }
      if (result.mfa) {
        setPendingMfa(result.mfa);
        setStatusMsg("");
        return;
      }
      setStatusMsg(t("status.loginIncomplete"));
    } catch (error) {
      setStatusMsg(apiErrorMessage(error, tSecurity, "apiErrors", t("status.loginFailed")));
    } finally {
      setLoading(false);
    }
  }

  async function verifyPasskey() {
    if (!pendingMfa) return;
    setLoading(true);
    setStatusMsg(t("status.passkeyChecking"));
    try {
      const start = await browserApiFetch<PasskeyAssertionStart>("/api/admin/auth/mfa/passkey/start", {
        method: "POST",
        body: JSON.stringify({ ticket: pendingMfa.ticket }),
      });
      const credential = await getPasskeyAssertion(start.public_key);
      const result = await browserApiFetch<AdminLoginResponse>("/api/admin/auth/mfa/passkey/verify", {
        method: "POST",
        body: JSON.stringify({ flow_token: start.flow_token, credential }),
      });
      if (result.authenticated) {
        finishLogin();
        return;
      }
      setStatusMsg(t("status.passkeyFailed"));
    } catch (error) {
      setStatusMsg(apiErrorMessage(error, tSecurity, "apiErrors", t("status.passkeyFailed")));
    } finally {
      setLoading(false);
    }
  }

  async function setupPasskey() {
    if (!pendingMfa) return;
    setLoading(true);
    setStatusMsg(t("status.passkeySetupPreparing"));
    try {
      const start = await browserApiFetch<PasskeyRegistrationStart>("/api/admin/auth/mfa/passkey/setup/start", {
        method: "POST",
        body: JSON.stringify({ ticket: pendingMfa.ticket }),
      });
      const credential = await createPasskeyCredential(start.public_key);
      const result = await browserApiFetch<AdminLoginResponse>("/api/admin/auth/mfa/passkey/setup/complete", {
        method: "POST",
        body: JSON.stringify({ flow_token: start.flow_token, label: passkeyLabel || null, credential }),
      });
      if (result.authenticated) {
        finishLogin();
        return;
      }
      setStatusMsg(t("status.passkeySetupFailed"));
    } catch (error) {
      setStatusMsg(apiErrorMessage(error, tSecurity, "apiErrors", t("status.passkeySetupFailed")));
    } finally {
      setLoading(false);
    }
  }

  function renderPasswordStep() {
    return (
      <form className="grid" onSubmit={submit}>
        <label className="field-stack">
          <span className="field-label">{t("email")}</span>
          <input value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("password")}</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
        </label>
        <button type="submit" className="button-secondary" disabled={loading}>
          {loading ? "…" : t("submit")}
        </button>
      </form>
    );
  }

  function renderBackButton() {
    return (
      <div className="table-actions table-actions-start">
        <button type="button" className="button-secondary button-ghost login-secondary-button" onClick={resetMfaFlow}>
          {t("backToLogin")}
        </button>
      </div>
    );
  }

  function renderSetupStep() {
    if (!pendingMfa) return null;
    return (
      <div className="grid">
        <div className="security-summary-card">
          <div>
            <div className="eyebrow">{t("mandatorySetupEyebrow")}</div>
            <strong>{t("passkeyRequiredTitle")}</strong>
            <div className="muted">{t("passkeyRequiredDescription", { user: pendingMfa.user_display_name })}</div>
          </div>
        </div>
        {passkeysSupported ? (
          <>
            <label className="field-stack">
              <span className="field-label">{t("passkeyLabel")}</span>
              <input value={passkeyLabel} onChange={(event) => setPasskeyLabel(event.target.value)} placeholder={t("passkeyLabelPlaceholder")} />
            </label>
            <button type="button" className="button-secondary" onClick={() => void setupPasskey()} disabled={loading}>
              {loading ? t("checking") : t("setupPasskeyAndLogin")}
            </button>
          </>
        ) : (
          <div className="info-note">{t("passkeyUnsupported")}</div>
        )}
        {renderBackButton()}
      </div>
    );
  }

  function renderVerifyStep() {
    if (!pendingMfa) return null;
    return (
      <div className="grid">
        <div className="login-heading">
          <p className="login-subtitle">{pendingMfa.user_email}</p>
        </div>
        <p className="muted">{t("passkeyVerifyHint")}</p>
        {passkeysSupported ? (
          <button type="button" className="button-secondary" onClick={() => void verifyPasskey()} disabled={loading} autoFocus>
            {loading ? t("checking") : t("verifyWithPasskey")}
          </button>
        ) : (
          <div className="info-note">{t("passkeyUnsupported")}</div>
        )}
        {renderBackButton()}
      </div>
    );
  }

  return (
    <main className="login-frame">
      <section className="login-panel">
        <div className="eyebrow">hocX Platform-Admin</div> {/* i18n-ok: Produktname/Bereichsbezeichnung, keine Uebersetzung */}
        <h1>{t("title")}</h1>

        {!pendingMfa ? renderPasswordStep() : pendingMfa.status === "setup_required" ? renderSetupStep() : renderVerifyStep()}

        {statusMsg && <p className="muted" role="alert">{statusMsg}</p>}
      </section>
      <CopyrightNotice className="login-copyright" />
    </main>
  );
}
