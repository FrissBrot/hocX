"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { attemptBridgeRedirect } from "@/lib/bridge-redirect";
import { browserApiFetch } from "@/lib/api/client";
import { getRuntimeConfig } from "@/lib/runtime-config";
import { browserSupportsPasskeys, createPasskeyCredential, getPasskeyAssertion } from "@/lib/webauthn";
import { LoginResponse, PasskeyAssertionStart, PasskeyRegistrationStart, PendingMfaLogin, SessionInfo, TotpEnrollmentStart } from "@/types/api";

type ResolvedTenant = { tenant_id: number; tenant_name: string; profile_image_url: string | null };

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [resolvedTenant, setResolvedTenant] = useState<ResolvedTenant | null>(null);
  const [statusMsg, setStatusMsg] = useState("");
  const [loading, setLoading] = useState(false);
  const [pendingMfa, setPendingMfa] = useState<PendingMfaLogin | null>(null);
  const [activeMethod, setActiveMethod] = useState<"totp" | "webauthn">("totp");
  const [totpCode, setTotpCode] = useState("");
  const [totpLabel, setTotpLabel] = useState("");
  const [totpSetup, setTotpSetup] = useState<TotpEnrollmentStart | null>(null);
  const [passkeyLabel, setPasskeyLabel] = useState("");
  const [appVersion, setAppVersion] = useState("");
  const resolvedTenantPromise = useRef<Promise<ResolvedTenant | null>>(Promise.resolve(null));

  const canUsePasskeys = browserSupportsPasskeys();
  const hasTotp = useMemo(
    () => pendingMfa?.available_methods.some((method) => method.factor_type === "totp") ?? false,
    [pendingMfa]
  );
  const hasPasskey = useMemo(
    () => pendingMfa?.available_methods.some((method) => method.factor_type === "webauthn") ?? false,
    [pendingMfa]
  );

  useEffect(() => {
    const mainDomain = getRuntimeConfig().mainAppDomain;
    if (mainDomain && window.location.hostname !== mainDomain) {
      window.location.replace(`https://${mainDomain}/login?from=${encodeURIComponent(window.location.hostname)}`);
    }
  }, []);

  useEffect(() => {
    setAppVersion(getRuntimeConfig().version);
  }, []);

  useEffect(() => {
    const fromDomain = new URLSearchParams(window.location.search).get("from");
    if (!fromDomain) return;
    const promise = browserApiFetch<ResolvedTenant>(`/api/auth/tenant-by-domain?domain=${encodeURIComponent(fromDomain)}`)
      .then((tenant) => {
        setResolvedTenant(tenant);
        return tenant;
      })
      .catch(() => null);
    resolvedTenantPromise.current = promise;
  }, []);

  useEffect(() => {
    async function init() {
      try {
        const session = await browserApiFetch<SessionInfo>("/api/auth/session");
        if (session.authenticated) {
          router.replace("/");
        }
      } catch {}
    }
    void init();
  }, [router]);

  useEffect(() => {
    if (!pendingMfa) {
      return;
    }
    if (pendingMfa.status === "setup_required") {
      setActiveMethod(canUsePasskeys && pendingMfa.can_add_passkey ? "webauthn" : "totp");
      return;
    }
    if (canUsePasskeys && hasPasskey) {
      setActiveMethod("webauthn");
      return;
    }
    setActiveMethod("totp");
  }, [canUsePasskeys, hasPasskey, pendingMfa]);

  function resetMfaFlow() {
    setPendingMfa(null);
    setTotpSetup(null);
    setTotpCode("");
    setTotpLabel("");
    setPasskeyLabel("");
    setStatusMsg("");
  }

  function finishLogin(session: LoginResponse) {
    if (session.bridge_redirect_url && attemptBridgeRedirect(session.bridge_redirect_url)) {
      return;
    }
    router.replace("/");
  }

  async function submitLocal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setStatusMsg("Anmeldung läuft…");
    try {
      const tenant = await resolvedTenantPromise.current;
      const session = await browserApiFetch<LoginResponse>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password, tenant_id: tenant?.tenant_id ?? null }),
      });
      if (session.authenticated) {
        finishLogin(session);
        return;
      }
      if (session.mfa) {
        setPendingMfa(session.mfa);
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

  async function verifyTotp() {
    if (!pendingMfa) return;
    setLoading(true);
    setStatusMsg("TOTP wird geprüft…");
    try {
      const session = await browserApiFetch<LoginResponse>("/api/auth/mfa/totp/verify", {
        method: "POST",
        body: JSON.stringify({ ticket: pendingMfa.ticket, code: totpCode }),
      });
      finishLogin(session);
    } catch (error) {
      setStatusMsg(error instanceof Error ? error.message : "TOTP-Prüfung fehlgeschlagen");
    } finally {
      setLoading(false);
    }
  }

  async function startTotpSetup() {
    if (!pendingMfa) return;
    setLoading(true);
    setStatusMsg("TOTP-Setup wird vorbereitet…");
    try {
      const setup = await browserApiFetch<TotpEnrollmentStart>("/api/auth/mfa/totp/setup/start", {
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

  async function completeTotpSetup() {
    if (!totpSetup) return;
    setLoading(true);
    setStatusMsg("TOTP wird aktiviert…");
    try {
      const session = await browserApiFetch<LoginResponse>("/api/auth/mfa/totp/setup/complete", {
        method: "POST",
        body: JSON.stringify({
          flow_token: totpSetup.flow_token,
          code: totpCode,
          label: totpLabel || null,
        }),
      });
      finishLogin(session);
    } catch (error) {
      setStatusMsg(error instanceof Error ? error.message : "TOTP konnte nicht aktiviert werden");
    } finally {
      setLoading(false);
    }
  }

  async function runPasskeyFlow() {
    if (!pendingMfa) return;
    setLoading(true);
    setStatusMsg(pendingMfa.status === "setup_required" ? "Passkey wird eingerichtet…" : "Passkey wird geprüft…");
    try {
      if (pendingMfa.status === "setup_required") {
        const start = await browserApiFetch<PasskeyRegistrationStart>("/api/auth/mfa/passkeys/setup/start", {
          method: "POST",
          body: JSON.stringify({ ticket: pendingMfa.ticket }),
        });
        const credential = await createPasskeyCredential(start.public_key);
        const session = await browserApiFetch<LoginResponse>("/api/auth/mfa/passkeys/setup/complete", {
          method: "POST",
          body: JSON.stringify({
            flow_token: start.flow_token,
            label: passkeyLabel || null,
            credential,
          }),
        });
        finishLogin(session);
        return;
      }

      const start = await browserApiFetch<PasskeyAssertionStart>("/api/auth/mfa/passkeys/assertion/start", {
        method: "POST",
        body: JSON.stringify({ ticket: pendingMfa.ticket }),
      });
      const credential = await getPasskeyAssertion(start.public_key);
      const session = await browserApiFetch<LoginResponse>("/api/auth/mfa/passkeys/assertion/verify", {
        method: "POST",
        body: JSON.stringify({
          flow_token: start.flow_token,
          credential,
        }),
      });
      finishLogin(session);
    } catch (error) {
      setStatusMsg(error instanceof Error ? error.message : "Passkey-Vorgang fehlgeschlagen");
    } finally {
      setLoading(false);
    }
  }

  function renderPasswordStep() {
    return (
      <form className="login-form" onSubmit={submitLocal}>
        <label className="field-stack">
          <span className="field-label">E-Mail</span>
          <input className="input" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </label>
        <label className="field-stack">
          <span className="field-label">Passwort</span>
          <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
        </label>
        <button type="submit" className="button-inline login-submit" disabled={loading}>
          {loading ? "…" : "Einloggen"}
        </button>
      </form>
    );
  }

  function renderSetupStep() {
    if (!pendingMfa) return null;
    return (
      <div className="grid">
        <div className="security-summary-card">
          <div>
            <div className="eyebrow">Pflicht-Setup</div>
            <strong>Für dieses Konto ist MFA erforderlich</strong>
            <div className="muted">
              {pendingMfa.tenant_name
                ? `${pendingMfa.user_display_name} ist Administrator in ${pendingMfa.tenant_name}.`
                : `${pendingMfa.user_display_name} benötigt vor dem Login einen zweiten Faktor.`}
            </div>
          </div>
        </div>

        <div className="wizard-steps">
          <div className="wizard-step">
            <div className="wizard-step-dot is-done">1</div>
            <div className="wizard-step-label is-active">Methode wählen</div>
          </div>
          <div className="wizard-step-line is-done" />
          <div className="wizard-step">
            <div className={`wizard-step-dot${totpSetup || activeMethod === "webauthn" ? " is-active" : ""}`}>2</div>
            <div className="wizard-step-label">Bestätigen</div>
          </div>
          <div className="wizard-step-line" />
          <div className="wizard-step">
            <div className="wizard-step-dot">3</div>
            <div className="wizard-step-label">Fertig anmelden</div>
          </div>
        </div>

        <div className="login-mfa-methods">
          <button
            type="button"
            className={activeMethod === "totp" ? "wizard-purpose-card is-selected" : "wizard-purpose-card"}
            onClick={() => setActiveMethod("totp")}
          >
            <div className="wizard-purpose-title">TOTP</div>
            <div className="wizard-purpose-desc">Authenticator-App auf Handy oder Desktop</div>
          </button>
          <button
            type="button"
            className={activeMethod === "webauthn" ? "wizard-purpose-card is-selected" : "wizard-purpose-card"}
            onClick={() => setActiveMethod("webauthn")}
            disabled={!pendingMfa.can_add_passkey || !canUsePasskeys}
          >
            <div className="wizard-purpose-title">Passkey</div>
            <div className="wizard-purpose-desc">
              {canUsePasskeys && pendingMfa.can_add_passkey ? "Face ID, Touch ID oder Windows Hello" : "In diesem Browser oder auf dieser Domain nicht verfügbar"}
            </div>
          </button>
        </div>

        {activeMethod === "totp" ? (
          <article className="security-method-card">
            <div className="security-method-header">
              <div>
                <div className="eyebrow">Schritt für Schritt</div>
                <h3>TOTP einrichten</h3>
              </div>
              <span className="pill">Pflicht</span>
            </div>
            {!totpSetup ? (
              <button type="button" className="button-inline" onClick={() => void startTotpSetup()} disabled={loading}>
                TOTP-Setup starten
              </button>
            ) : (
              <div className="grid">
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
                  <input value={totpCode} onChange={(event) => setTotpCode(event.target.value)} inputMode="numeric" placeholder="123456" />
                </label>
                <button type="button" className="button-inline" disabled={!totpCode || loading} onClick={() => void completeTotpSetup()}>
                  {loading ? "Wird aktiviert…" : "TOTP aktivieren und anmelden"}
                </button>
              </div>
            )}
          </article>
        ) : (
          <article className="security-method-card">
            <div className="security-method-header">
              <div>
                <div className="eyebrow">Schritt für Schritt</div>
                <h3>Passkey einrichten</h3>
              </div>
              <span className="pill">Empfohlen</span>
            </div>
            <p className="muted">
              Dein Gerät öffnet gleich den nativen Sicherheitsdialog. Nach der Bestätigung wirst du direkt angemeldet.
            </p>
            <label className="field-stack">
              <span className="field-label">Bezeichnung</span>
              <input value={passkeyLabel} onChange={(event) => setPasskeyLabel(event.target.value)} placeholder="z.B. Arbeitslaptop" />
            </label>
            <button type="button" className="button-inline" disabled={loading || !canUsePasskeys || !pendingMfa.can_add_passkey} onClick={() => void runPasskeyFlow()}>
              {loading ? "Passkey wird eingerichtet…" : "Passkey einrichten und anmelden"}
            </button>
          </article>
        )}
      </div>
    );
  }

  function renderVerifyStep() {
    if (!pendingMfa) return null;
    return (
      <div className="grid">
        <div className="security-summary-card">
          <div>
            <div className="eyebrow">Zweiter Faktor</div>
            <strong>Bitte bestätige deine Anmeldung</strong>
            <div className="muted">
              {pendingMfa.user_display_name} hat bereits MFA aktiviert. Wähle jetzt eine der verfügbaren Methoden.
            </div>
          </div>
          <div className="status-row">
            {pendingMfa.available_methods.map((method) => (
              <span key={method.factor_type} className="pill">
                {method.label}
              </span>
            ))}
          </div>
        </div>

        <div className="login-mfa-methods">
          {hasTotp ? (
            <button
              type="button"
              className={activeMethod === "totp" ? "wizard-purpose-card is-selected" : "wizard-purpose-card"}
              onClick={() => setActiveMethod("totp")}
            >
              <div className="wizard-purpose-title">TOTP</div>
              <div className="wizard-purpose-desc">Code aus deiner Authenticator-App</div>
            </button>
          ) : null}
          {hasPasskey ? (
            <button
              type="button"
              className={activeMethod === "webauthn" ? "wizard-purpose-card is-selected" : "wizard-purpose-card"}
              onClick={() => setActiveMethod("webauthn")}
              disabled={!canUsePasskeys}
            >
              <div className="wizard-purpose-title">Passkey</div>
              <div className="wizard-purpose-desc">
                {canUsePasskeys ? "Mit Gerätebiometrie bestätigen" : "Dieser Browser unterstützt keine Passkeys"}
              </div>
            </button>
          ) : null}
        </div>

        {activeMethod === "totp" ? (
          <article className="security-method-card">
            <div className="security-method-header">
              <div>
                <div className="eyebrow">Anmeldung</div>
                <h3>TOTP-Code eingeben</h3>
              </div>
            </div>
            <label className="field-stack">
              <span className="field-label">6-stelliger Code</span>
              <input value={totpCode} onChange={(event) => setTotpCode(event.target.value)} inputMode="numeric" placeholder="123456" />
            </label>
            <button type="button" className="button-inline" disabled={!totpCode || loading} onClick={() => void verifyTotp()}>
              {loading ? "Wird geprüft…" : "Mit TOTP anmelden"}
            </button>
          </article>
        ) : (
          <article className="security-method-card">
            <div className="security-method-header">
              <div>
                <div className="eyebrow">Anmeldung</div>
                <h3>Mit Passkey fortfahren</h3>
              </div>
            </div>
            <p className="muted">
              Nach dem Klick öffnet dein Gerät den Passkey-Dialog. Bestätige dort die Anmeldung.
            </p>
            <button type="button" className="button-inline" disabled={loading || !canUsePasskeys} onClick={() => void runPasskeyFlow()}>
              {loading ? "Passkey wird geprüft…" : "Mit Passkey anmelden"}
            </button>
          </article>
        )}
      </div>
    );
  }

  return (
    <main className="login-frame">
      <section className={pendingMfa ? "login-panel login-panel-wide" : "login-panel"}>
        <div className="login-brand">
          <div className={`login-avatar${resolvedTenant?.profile_image_url ? "" : " login-avatar-fallback"}`}>
            {resolvedTenant?.profile_image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={resolvedTenant.profile_image_url} alt={resolvedTenant.tenant_name} />
            ) : (
              <span>hX</span>
            )}
          </div>
          <div className="eyebrow">hocX</div>
        </div>

        <div className="login-heading">
          <h1>{pendingMfa ? "Sicher anmelden" : "Anmelden bei hocX"}</h1>
          {resolvedTenant && !pendingMfa ? <p className="login-subtitle">für {resolvedTenant.tenant_name}</p> : null}
          {pendingMfa ? <p className="login-subtitle">{pendingMfa.user_email}</p> : null}
        </div>

        {!pendingMfa ? renderPasswordStep() : pendingMfa.status === "setup_required" ? renderSetupStep() : renderVerifyStep()}

        {pendingMfa ? (
          <div className="table-actions table-actions-start">
            <button type="button" className="button-inline button-ghost" onClick={resetMfaFlow}>
              Zurück zum Login
            </button>
          </div>
        ) : null}

        {statusMsg && <p className="login-status">{statusMsg}</p>}
      </section>
      {appVersion && <p className="login-version">hocX {appVersion}</p>}
    </main>
  );
}
