"use client";

import { ChangeEvent, ClipboardEvent, FormEvent, KeyboardEvent, SVGProps, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { attemptBridgeRedirect } from "@/lib/bridge-redirect";
import { browserApiFetch } from "@/lib/api/client";
import { getRuntimeConfig } from "@/lib/runtime-config";
import { browserSupportsPasskeys, createPasskeyCredential, getPasskeyAssertion } from "@/lib/webauthn";
import { LoginResponse, PasskeyAssertionStart, PasskeyRegistrationStart, PendingMfaLogin, SessionInfo, TotpEnrollmentStart } from "@/types/api";

type ResolvedTenant = { tenant_id: number; tenant_name: string; profile_image_url: string | null };
const MFA_CODE_LENGTH = 6;

type IconProps = Omit<SVGProps<SVGSVGElement>, "viewBox" | "fill">;

function MfaPasskeyIcon(props: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <circle cx="11" cy="8" r="3.3" />
      <path d="M5.2 18.4c0-3.2 2.6-5.8 5.8-5.8s5.8 2.6 5.8 5.8" />
      <path d="M16.8 10.6l2.1 2.1" />
      <path d="M18.9 12.7v2.3" />
      <path d="M18.9 12.7h2.3" />
    </svg>
  );
}

function MfaCodeIcon(props: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <rect x="4.5" y="10" width="15" height="9.5" rx="2.2" />
      <path d="M8 10V7.8A4 4 0 0112 4a4 4 0 014 3.8V10" />
    </svg>
  );
}

function sanitizeTotpCode(value: string) {
  return value.replace(/\D/g, "").slice(0, MFA_CODE_LENGTH);
}

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
  const [showMethodChooser, setShowMethodChooser] = useState(false);
  const resolvedTenantPromise = useRef<Promise<ResolvedTenant | null>>(Promise.resolve(null));
  const autoStartedPasskeyTicketRef = useRef<string | null>(null);
  const totpDigitRefs = useRef<Array<HTMLInputElement | null>>([]);

  const canUsePasskeys = browserSupportsPasskeys();
  const hasTotp = useMemo(
    () => pendingMfa?.available_methods.some((method) => method.factor_type === "totp") ?? false,
    [pendingMfa]
  );
  const hasPasskey = useMemo(
    () => pendingMfa?.available_methods.some((method) => method.factor_type === "webauthn") ?? false,
    [pendingMfa]
  );
  const canDirectToTotp = hasTotp;
  const canDirectToPasskey = hasPasskey && (canUsePasskeys || !hasTotp);
  const hasDirectDefaultMethod =
    pendingMfa?.default_factor_type === "totp"
      ? canDirectToTotp
      : pendingMfa?.default_factor_type === "webauthn"
        ? canDirectToPasskey
        : false;
  const directMethodCount = Number(canDirectToTotp) + Number(canDirectToPasskey);
  const shouldRequireMethodChoice = pendingMfa?.status === "verification_required" ? !hasDirectDefaultMethod && directMethodCount > 1 : false;
  const totpDigits = useMemo(
    () => Array.from({ length: MFA_CODE_LENGTH }, (_, index) => totpCode[index] ?? ""),
    [totpCode]
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
      setShowMethodChooser(false);
      autoStartedPasskeyTicketRef.current = null;
      return;
    }
    if (pendingMfa.status === "setup_required") {
      setShowMethodChooser(false);
      setActiveMethod(canUsePasskeys && pendingMfa.can_add_passkey ? "webauthn" : "totp");
      return;
    }
    setShowMethodChooser(shouldRequireMethodChoice);
    if (pendingMfa.default_factor_type === "webauthn" && hasPasskey && (canUsePasskeys || !hasTotp)) {
      setActiveMethod("webauthn");
      return;
    }
    if (pendingMfa.default_factor_type === "totp" && hasTotp) {
      setActiveMethod("totp");
      return;
    }
    if (canUsePasskeys && hasPasskey) {
      setActiveMethod("webauthn");
      return;
    }
    if (hasTotp) {
      setActiveMethod("totp");
      return;
    }
    if (hasPasskey) {
      setActiveMethod("webauthn");
      return;
    }
    setActiveMethod("totp");
  }, [canUsePasskeys, hasPasskey, hasTotp, pendingMfa, shouldRequireMethodChoice]);

  useEffect(() => {
    if (pendingMfa?.status !== "verification_required" || activeMethod !== "totp" || showMethodChooser) {
      return;
    }
    const firstEmptyIndex = totpDigits.findIndex((digit) => !digit);
    const focusIndex = firstEmptyIndex === -1 ? MFA_CODE_LENGTH - 1 : firstEmptyIndex;
    totpDigitRefs.current[focusIndex]?.focus();
    totpDigitRefs.current[focusIndex]?.select();
  }, [activeMethod, pendingMfa, showMethodChooser, totpDigits]);

  useEffect(() => {
    if (!pendingMfa || pendingMfa.status !== "verification_required") {
      return;
    }
    if (activeMethod !== "webauthn" || showMethodChooser || !hasPasskey || !canUsePasskeys || loading) {
      return;
    }
    if (autoStartedPasskeyTicketRef.current === pendingMfa.ticket) {
      return;
    }
    autoStartedPasskeyTicketRef.current = pendingMfa.ticket;
    void runPasskeyFlow("auto");
  }, [activeMethod, canUsePasskeys, hasPasskey, loading, pendingMfa, showMethodChooser]);

  function resetMfaFlow() {
    setPendingMfa(null);
    setTotpSetup(null);
    setTotpCode("");
    setTotpLabel("");
    setPasskeyLabel("");
    setShowMethodChooser(false);
    autoStartedPasskeyTicketRef.current = null;
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
        setTotpCode("");
        setShowMethodChooser(false);
        autoStartedPasskeyTicketRef.current = null;
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
    setStatusMsg("Code wird geprüft…");
    try {
      const session = await browserApiFetch<LoginResponse>("/api/auth/mfa/totp/verify", {
        method: "POST",
        body: JSON.stringify({ ticket: pendingMfa.ticket, code: totpCode }),
      });
      finishLogin(session);
    } catch (error) {
      setStatusMsg(error instanceof Error ? error.message : "Code-Prüfung fehlgeschlagen");
    } finally {
      setLoading(false);
    }
  }

  function setTotpDigitValue(index: number, nextValue: string) {
    const digits = sanitizeTotpCode(nextValue);
    setTotpCode((current) => {
      const nextDigits = Array.from({ length: MFA_CODE_LENGTH }, (_, currentIndex) => current[currentIndex] ?? "");
      if (!digits) {
        nextDigits[index] = "";
        return nextDigits.join("");
      }
      digits.split("").forEach((digit, offset) => {
        const targetIndex = index + offset;
        if (targetIndex < MFA_CODE_LENGTH) {
          nextDigits[targetIndex] = digit;
        }
      });
      return nextDigits.join("");
    });

    if (!digits) {
      return;
    }

    const focusIndex = Math.min(index + digits.length, MFA_CODE_LENGTH - 1);
    requestAnimationFrame(() => {
      totpDigitRefs.current[focusIndex]?.focus();
      totpDigitRefs.current[focusIndex]?.select();
    });
  }

  function handleTotpDigitChange(index: number, event: ChangeEvent<HTMLInputElement>) {
    setTotpDigitValue(index, event.target.value);
  }

  function handleTotpDigitKeyDown(index: number, event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Backspace") {
      event.preventDefault();
      setTotpCode((current) => {
        const nextDigits = Array.from({ length: MFA_CODE_LENGTH }, (_, currentIndex) => current[currentIndex] ?? "");
        if (nextDigits[index]) {
          nextDigits[index] = "";
          return nextDigits.join("");
        }
        if (index > 0) {
          nextDigits[index - 1] = "";
          requestAnimationFrame(() => {
            totpDigitRefs.current[index - 1]?.focus();
            totpDigitRefs.current[index - 1]?.select();
          });
        }
        return nextDigits.join("");
      });
      return;
    }

    if (event.key === "ArrowLeft" && index > 0) {
      event.preventDefault();
      totpDigitRefs.current[index - 1]?.focus();
      totpDigitRefs.current[index - 1]?.select();
      return;
    }

    if (event.key === "ArrowRight" && index < MFA_CODE_LENGTH - 1) {
      event.preventDefault();
      totpDigitRefs.current[index + 1]?.focus();
      totpDigitRefs.current[index + 1]?.select();
      return;
    }

    if (event.key === "Home") {
      event.preventDefault();
      totpDigitRefs.current[0]?.focus();
      totpDigitRefs.current[0]?.select();
      return;
    }

    if (event.key === "End") {
      event.preventDefault();
      totpDigitRefs.current[MFA_CODE_LENGTH - 1]?.focus();
      totpDigitRefs.current[MFA_CODE_LENGTH - 1]?.select();
    }
  }

  function handleTotpPaste(index: number, event: ClipboardEvent<HTMLInputElement>) {
    const pastedDigits = sanitizeTotpCode(event.clipboardData.getData("text"));
    if (!pastedDigits) {
      return;
    }
    event.preventDefault();
    setTotpDigitValue(index, pastedDigits);
  }

  function selectVerificationMethod(method: "totp" | "webauthn") {
    setActiveMethod(method);
    setShowMethodChooser(false);
    setStatusMsg("");
  }

  function openMethodChooser() {
    setShowMethodChooser(true);
    setStatusMsg("");
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

  async function runPasskeyFlow(mode: "auto" | "manual" = "manual") {
    if (!pendingMfa) return;
    setLoading(true);
    setStatusMsg(
      pendingMfa.status === "setup_required"
        ? "Passkey wird eingerichtet…"
        : mode === "auto"
          ? "Passkey-Dialog wird geöffnet…"
          : "Passkey wird geprüft…"
    );
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
                  <input value={totpCode} onChange={(event) => setTotpCode(sanitizeTotpCode(event.target.value))} inputMode="numeric" placeholder="123456" />
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
    const canSwitchMethods = pendingMfa.available_methods.length > 1;
    if (showMethodChooser) {
      return (
        <div className="mfa-screen mfa-screen-choice">
          <div className="mfa-screen-header mfa-screen-header-left">
            <h1>Anmeldemethode wählen</h1>
            <p>Wähle, wie du deine Identität bestätigen möchtest.</p>
          </div>

          <div className="mfa-choice-list">
            {hasPasskey ? (
              <button
                type="button"
                className="mfa-choice-card"
                onClick={() => selectVerificationMethod("webauthn")}
                disabled={!canUsePasskeys}
              >
                <span className="mfa-choice-icon mfa-choice-icon-passkey">
                  <MfaPasskeyIcon width={28} height={28} />
                </span>
                <span className="mfa-choice-copy">
                  <strong>Passkey</strong>
                  <span>
                    {canUsePasskeys
                      ? "Mit Face ID, Fingerabdruck oder Gerätecode"
                      : "In diesem Browser oder auf dieser Domain nicht verfügbar"}
                  </span>
                </span>
              </button>
            ) : null}
            {hasTotp ? (
              <button type="button" className="mfa-choice-card" onClick={() => selectVerificationMethod("totp")}>
                <span className="mfa-choice-icon">
                  <MfaCodeIcon width={28} height={28} />
                </span>
                <span className="mfa-choice-copy">
                  <strong>Code</strong>
                  <span>Aus deiner Authenticator-App eingeben</span>
                </span>
              </button>
            ) : null}
          </div>

          <div className="mfa-footer-stack">
            <button type="button" className="button-inline button-ghost login-secondary-button login-secondary-button-centered" onClick={resetMfaFlow}>
              Zurück zur Anmeldung
            </button>
          </div>
        </div>
      );
    }

    if (activeMethod === "totp") {
      return (
        <div className="mfa-screen mfa-screen-code">
          <div className="mfa-icon-badge mfa-icon-badge-large mfa-icon-badge-left">
            <MfaCodeIcon width={34} height={34} />
          </div>

          <div className="mfa-screen-header mfa-screen-header-left">
            <h1>Bestätigungscode eingeben</h1>
            <p>Gib den 6-stelligen Code aus deiner Authenticator-App ein.</p>
          </div>

          <form
            className="mfa-code-form"
            onSubmit={(event) => {
              event.preventDefault();
              void verifyTotp();
            }}
          >
            <div className="mfa-code-inputs">
              {totpDigits.map((digit, index) => (
                <input
                  key={index}
                  ref={(node) => {
                    totpDigitRefs.current[index] = node;
                  }}
                  className="mfa-code-input"
                  value={digit}
                  onChange={(event) => handleTotpDigitChange(index, event)}
                  onKeyDown={(event) => handleTotpDigitKeyDown(index, event)}
                  onPaste={(event) => handleTotpPaste(index, event)}
                  onFocus={(event) => event.currentTarget.select()}
                  inputMode="numeric"
                  autoComplete={index === 0 ? "one-time-code" : "off"}
                  aria-label={`Code-Ziffer ${index + 1}`}
                  maxLength={1}
                />
              ))}
            </div>

            <button type="submit" className="button-inline login-submit mfa-primary-button" disabled={totpCode.length !== MFA_CODE_LENGTH || loading}>
              {loading ? "Prüft…" : "Bestätigen"}
            </button>
          </form>

          <div className={`mfa-footer-links${canSwitchMethods ? " mfa-footer-links-split" : ""}`}>
            <button type="button" className="button-inline button-ghost login-secondary-button" onClick={resetMfaFlow}>
              Zurück zur Anmeldung
            </button>
            {canSwitchMethods ? (
              <button type="button" className="button-inline button-ghost login-secondary-button" onClick={openMethodChooser}>
                Andere Option wählen
              </button>
            ) : null}
          </div>
        </div>
      );
    }

    return (
      <div className="mfa-screen mfa-screen-passkey">
        <div className="mfa-icon-badge mfa-icon-badge-xl">
          <MfaPasskeyIcon width={40} height={40} />
        </div>

        <div className="mfa-screen-header mfa-screen-header-center">
          <h1>Passkey bestätigen</h1>
          <p>Folge den Anweisungen deines Geräts, um dich mit Face ID, Fingerabdruck oder Gerätecode anzumelden.</p>
        </div>

        <button
          type="button"
          className="button-inline login-submit mfa-primary-button"
          disabled={loading || !canUsePasskeys}
          onClick={() => void runPasskeyFlow("manual")}
        >
          {loading ? "Öffnet…" : canUsePasskeys ? "Weiter" : "Passkey nicht verfügbar"}
        </button>

        <div className="mfa-footer-stack">
          {canSwitchMethods ? (
            <button type="button" className="button-inline button-ghost login-secondary-button login-secondary-button-centered" onClick={openMethodChooser}>
              Andere Option wählen
            </button>
          ) : null}
          <button type="button" className="button-inline button-ghost login-secondary-button login-secondary-button-centered" onClick={resetMfaFlow}>
            Zurück zur Anmeldung
          </button>
        </div>
      </div>
    );
  }

  const isVerifyScreen = pendingMfa?.status === "verification_required";
  const loginPanelClassName = pendingMfa?.status === "setup_required" ? "login-panel login-panel-wide" : "login-panel";
  const loginTitle = pendingMfa?.status === "setup_required" ? "Sicher anmelden" : "Anmelden bei hocX";

  return (
    <main className="login-frame">
      <section className={loginPanelClassName}>
        {!isVerifyScreen ? (
          <>
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
              <h1>{loginTitle}</h1>
              {resolvedTenant && !pendingMfa ? <p className="login-subtitle">für {resolvedTenant.tenant_name}</p> : null}
              {pendingMfa ? <p className="login-subtitle">{pendingMfa.user_email}</p> : null}
            </div>
          </>
        ) : null}

        {!pendingMfa ? renderPasswordStep() : pendingMfa.status === "setup_required" ? renderSetupStep() : renderVerifyStep()}

        {pendingMfa?.status === "setup_required" ? (
          <div className="table-actions table-actions-start">
            <button type="button" className="button-inline button-ghost login-secondary-button" onClick={resetMfaFlow}>
              Zurück zum Login
            </button>
          </div>
        ) : null}

        {statusMsg && <p className={isVerifyScreen ? "login-status login-status-mfa" : "login-status"}>{statusMsg}</p>}
        {appVersion && isVerifyScreen ? <p className="login-version login-version-in-panel">hocX {appVersion}</p> : null}
      </section>
      {appVersion && !isVerifyScreen ? <p className="login-version">hocX {appVersion}</p> : null}
    </main>
  );
}
