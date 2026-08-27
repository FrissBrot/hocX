"use client";

import { FormEvent, useState } from "react";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { browserApiFetch, browserApiBaseUrl } from "@/lib/api/client";
import { AdminLoginResponse, AdminSessionInfo, PendingMfaLogin, PlatformOidcConfigPublic, TotpEnrollmentStart } from "@/types/api";
import { CopyrightNotice } from "@/components/ui/copyright-notice";

function sanitizeTotpCode(value: string) {
  return value.replace(/\D/g, "").slice(0, 6);
}

export default function AdminLoginPage() {
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
    setStatusMsg("Anmeldung läuft…");
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
      setStatusMsg("Login konnte nicht abgeschlossen werden.");
    } catch (error) {
      setStatusMsg(error instanceof Error ? error.message : "Login fehlgeschlagen");
    } finally {
      setLoading(false);
    }
  }

  async function verifyTotp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!pendingMfa) return;
    setLoading(true);
    setStatusMsg("Code wird geprüft…");
    try {
      const result = await browserApiFetch<AdminLoginResponse>("/api/admin/auth/mfa/totp/verify", {
        method: "POST",
        body: JSON.stringify({ ticket: pendingMfa.ticket, code: totpCode }),
      });
      if (result.authenticated) {
        finishLogin();
        return;
      }
      setStatusMsg("Code-Prüfung fehlgeschlagen.");
    } catch (error) {
      setStatusMsg(error instanceof Error ? error.message : "Code-Prüfung fehlgeschlagen");
    } finally {
      setLoading(false);
    }
  }

  async function startTotpSetup() {
    if (!pendingMfa) return;
    setLoading(true);
    setStatusMsg("TOTP-Setup wird vorbereitet…");
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
      setStatusMsg(error instanceof Error ? error.message : "TOTP-Setup konnte nicht gestartet werden");
    } finally {
      setLoading(false);
    }
  }

  async function completeTotpSetup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!totpSetup) return;
    setLoading(true);
    setStatusMsg("TOTP wird aktiviert…");
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
      setStatusMsg("TOTP konnte nicht aktiviert werden.");
    } catch (error) {
      setStatusMsg(error instanceof Error ? error.message : "TOTP konnte nicht aktiviert werden");
    } finally {
      setLoading(false);
    }
  }

  function renderPasswordStep() {
    return (
      <>
        {oidcConfig?.enabled && (
          <div className="login-sso">
            <button type="button" className="button-inline oidc-button" onClick={loginWithOidc}>
              Mit {new URL(oidcConfig.issuer_url).hostname} anmelden
            </button>
            <div className="login-divider"><span>oder</span></div>
          </div>
        )}

        <form className="grid" onSubmit={submit}>
          <label className="field-stack">
            <span className="field-label">E-Mail</span>
            <input value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
          </label>
          <label className="field-stack">
            <span className="field-label">Passwort</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
          </label>
          <button type="submit" className="button-inline" disabled={loading}>
            {loading ? "…" : "Einloggen"}
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
            <div className="eyebrow">Pflicht-Setup</div>
            <strong>Für Platform-Admin-Konten ist MFA erforderlich</strong>
            <div className="muted">{pendingMfa.user_display_name} benötigt vor dem Login einen zweiten Faktor (Authenticator-App).</div>
          </div>
        </div>

        {!totpSetup ? (
          <button type="button" className="button-inline" onClick={() => void startTotpSetup()} disabled={loading}>
            TOTP-Setup starten
          </button>
        ) : (
          <form className="grid" onSubmit={completeTotpSetup}>
            <div className="security-secret-card">
              <div className="field-label">Setup-Key</div>
              <code className="security-secret-value">{totpSetup.manual_entry_key}</code>
              <a href={totpSetup.provisioning_uri} className="button-inline button-ghost">
                In Authenticator-App öffnen
              </a>
            </div>
            <label className="field-stack">
              <span className="field-label">Bezeichnung</span>
              <input value={totpLabel} onChange={(event) => setTotpLabel(event.target.value)} placeholder="z.B. Firmenhandy" />
            </label>
            <label className="field-stack">
              <span className="field-label">6-stelligen Code eingeben</span>
              <input
                value={totpCode}
                onChange={(event) => setTotpCode(sanitizeTotpCode(event.target.value))}
                inputMode="numeric"
                placeholder="123456"
                autoComplete="one-time-code"
              />
            </label>
            <button type="submit" className="button-inline" disabled={totpCode.length !== 6 || loading}>
              {loading ? "Wird aktiviert…" : "TOTP aktivieren und anmelden"}
            </button>
          </form>
        )}

        <div className="table-actions table-actions-start">
          <button type="button" className="button-inline button-ghost login-secondary-button" onClick={resetMfaFlow}>
            Zurück zum Login
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
            <span className="field-label">Bestätigungscode aus der Authenticator-App</span>
            <input
              value={totpCode}
              onChange={(event) => setTotpCode(sanitizeTotpCode(event.target.value))}
              inputMode="numeric"
              placeholder="123456"
              autoComplete="one-time-code"
              autoFocus
            />
          </label>
          <button type="submit" className="button-inline" disabled={totpCode.length !== 6 || loading}>
            {loading ? "Prüft…" : "Bestätigen"}
          </button>
        </form>
        <div className="table-actions table-actions-start">
          <button type="button" className="button-inline button-ghost login-secondary-button" onClick={resetMfaFlow}>
            Zurück zum Login
          </button>
        </div>
      </div>
    );
  }

  return (
    <main className="login-frame">
      <section className="login-panel">
        <div className="eyebrow">hocX Platform-Admin</div>
        <h1>Admin-Anmeldung</h1>

        {!pendingMfa ? renderPasswordStep() : pendingMfa.status === "setup_required" ? renderSetupStep() : renderVerifyStep()}

        {statusMsg && <p className="muted">{statusMsg}</p>}
      </section>
      <CopyrightNotice className="login-copyright" />
    </main>
  );
}
