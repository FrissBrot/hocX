"use client";

import { FormEvent, useState } from "react";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { browserApiFetch, browserApiBaseUrl } from "@/lib/api/client";
import { AdminLoginResponse, AdminSessionInfo, PendingMfaLogin, PlatformOidcConfigPublic, TotpEnrollmentStart } from "@/types/api";
import { CopyrightNotice } from "@/components/ui/copyright-notice";
import { TotpEnrollCard } from "@/components/security/totp-enroll-card";

function sanitizeTotpCode(value: string) {
  return value.replace(/\D/g, "").slice(0, 6);
}

export default function AdminLoginPage() {
  const t = useTranslations("admin.login");
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [oidcConfig, setOidcConfig] = useState<PlatformOidcConfigPublic | null>(null);
  const [statusMsg, setStatusMsg] = useState("");
  const [loading, setLoading] = useState(false);
  const [pendingMfa, setPendingMfa] = useState<PendingMfaLogin | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [totpLabel, setTotpLabel] = useState("");
  const [totpSetup, setTotpSetup] = useState<TotpEnrollmentStart | null>(null);

  useEffect(() => {
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

  useEffect(() => {
    async function loadOidc() {
      try {
        const cfg = await browserApiFetch<PlatformOidcConfigPublic>("/api/admin/auth/oidc/public-config");
        setOidcConfig(cfg ?? null);
      } catch {
        setOidcConfig(null);
      }
    }
    void loadOidc();
  }, []);

  function loginWithOidc() {
    window.location.href = `${browserApiBaseUrl}/api/admin/auth/oidc/authorize?redirect_to=/admin`;
  }

  function finishLogin() {
    // Nur replace(), kein zusätzliches refresh() - beide lösen sonst nahezu gleichzeitig
    // eine Server-Neuladen für die Zielroute aus, was zu einem kurzen Hin-und-Her zwischen
    // /admin/login und /admin führte (spürbar als Login-Loop, da staleTimes.dynamic=0 ohnehin
    // schon jede Navigation frisch vom Server lädt - refresh() ist hier redundant).
    router.replace("/admin");
  }

  function resetMfaFlow() {
    setPendingMfa(null);
    setTotpSetup(null);
    setTotpCode("");
    setTotpLabel("");
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
        setTotpCode("");
        setStatusMsg("");
        return;
      }
      setStatusMsg(t("status.loginIncomplete"));
    } catch (error) {
      setStatusMsg(error instanceof Error ? error.message : t("status.loginFailed"));
    } finally {
      setLoading(false);
    }
  }

  async function verifyTotp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!pendingMfa) return;
    setLoading(true);
    setStatusMsg(t("status.codeChecking"));
    try {
      const result = await browserApiFetch<AdminLoginResponse>("/api/admin/auth/mfa/totp/verify", {
        method: "POST",
        body: JSON.stringify({ ticket: pendingMfa.ticket, code: totpCode }),
      });
      if (result.authenticated) {
        finishLogin();
        return;
      }
      setStatusMsg(t("status.codeCheckFailed"));
    } catch (error) {
      setStatusMsg(error instanceof Error ? error.message : t("status.codeCheckFailed"));
    } finally {
      setLoading(false);
    }
  }

  async function startTotpSetup() {
    if (!pendingMfa) return;
    setLoading(true);
    setStatusMsg(t("status.totpSetupPreparing"));
    try {
      const setup = await browserApiFetch<TotpEnrollmentStart>("/api/admin/auth/mfa/totp/setup/start", {
        method: "POST",
        body: JSON.stringify({ ticket: pendingMfa.ticket }),
      });
      setTotpSetup(setup);
      setTotpCode("");
      setTotpLabel("");
      setStatusMsg("");
    } catch (error) {
      setStatusMsg(error instanceof Error ? error.message : t("status.totpSetupStartFailed"));
    } finally {
      setLoading(false);
    }
  }

  async function completeTotpSetup() {
    if (!totpSetup) return;
    setLoading(true);
    setStatusMsg(t("status.totpActivating"));
    try {
      const result = await browserApiFetch<AdminLoginResponse>("/api/admin/auth/mfa/totp/setup/complete", {
        method: "POST",
        body: JSON.stringify({
          flow_token: totpSetup.flow_token,
          code: totpCode,
          label: totpLabel || null,
        }),
      });
      if (result.authenticated) {
        finishLogin();
        return;
      }
      setStatusMsg(t("status.totpActivateFailed"));
    } catch (error) {
      setStatusMsg(error instanceof Error ? error.message : t("status.totpActivateFailed"));
    } finally {
      setLoading(false);
    }
  }

  function renderPasswordStep() {
    return (
      <>
        {oidcConfig?.enabled && (
          <div className="login-sso">
            <button type="button" className="button-secondary oidc-button" onClick={loginWithOidc}>
              {t("loginWithSso", { host: new URL(oidcConfig.issuer_url).hostname })}
            </button>
            <div className="login-divider"><span>{t("or")}</span></div>
          </div>
        )}

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
      </>
    );
  }

  function renderSetupStep() {
    if (!pendingMfa) return null;
    return (
      <div className="grid">
        <div className="security-summary-card">
          <div>
            <div className="eyebrow">{t("mandatorySetupEyebrow")}</div>
            <strong>{t("mfaRequiredTitle")}</strong>
            <div className="muted">{t("mfaRequiredDescription", { user: pendingMfa.user_display_name })}</div>
          </div>
        </div>

        {!totpSetup ? (
          <button type="button" className="button-secondary" onClick={() => void startTotpSetup()} disabled={loading}>
            {t("startTotpSetup")}
          </button>
        ) : (
          <TotpEnrollCard
            setup={totpSetup}
            label={totpLabel}
            onLabelChange={setTotpLabel}
            code={totpCode}
            onCodeChange={setTotpCode}
            onSubmit={() => void completeTotpSetup()}
            busy={loading}
            submitLabel={t("totpActivateAndLogin")}
            submitBusyLabel={t("totpActivatingShort")}
          />
        )}

        <div className="table-actions table-actions-start">
          <button type="button" className="button-secondary button-ghost login-secondary-button" onClick={resetMfaFlow}>
            {t("backToLogin")}
          </button>
        </div>
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
        <form className="grid" onSubmit={verifyTotp}>
          <label className="field-stack">
            <span className="field-label">{t("confirmationCodeLabel")}</span>
            <input
              value={totpCode}
              onChange={(event) => setTotpCode(sanitizeTotpCode(event.target.value))}
              inputMode="numeric"
              placeholder="123456"
              autoComplete="one-time-code"
              autoFocus
            />
          </label>
          <button type="submit" className="button-secondary" disabled={totpCode.length !== 6 || loading}>
            {loading ? t("checking") : t("confirmButton")}
          </button>
        </form>
        <div className="table-actions table-actions-start">
          <button type="button" className="button-secondary button-ghost login-secondary-button" onClick={resetMfaFlow}>
            {t("backToLogin")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <main className="login-frame">
      <section className="login-panel">
        <div className="eyebrow">hocX Platform-Admin</div> {/* i18n-ok: Produktname/Bereichsbezeichnung, keine Uebersetzung */}
        <h1>{t("title")}</h1>

        {!pendingMfa ? renderPasswordStep() : pendingMfa.status === "setup_required" ? renderSetupStep() : renderVerifyStep()}

        {statusMsg && <p className="muted">{statusMsg}</p>}
      </section>
      <CopyrightNotice className="login-copyright" />
    </main>
  );
}
