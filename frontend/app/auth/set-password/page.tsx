"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { apiErrorCode } from "@/lib/api/error-message";
import { attemptBridgeRedirect } from "@/lib/bridge-redirect";
import { evaluatePassword } from "@/lib/password-strength";
import { browserSupportsPasskeys } from "@/lib/webauthn";
import type { AccountLinkComplete, AccountLinkPreview, PendingMfaLogin } from "@/types/api";

import { FactorResult, InviteFactorStep } from "./invite-factor-step";
import { PasswordStrengthMeter } from "./password-strength-meter";

/**
 * Neues Passwort über einen Einmal-Link aus der E-Mail: «Passwort vergessen» oder Einladung
 * (Benachrichtigungen Phase 3, backend/app/notifications/account.py).
 *
 * Das Token kommt im URL-Fragment (`#token=…`, SECURITY-RULES 3.2): Der Browser schickt es an
 * keinen Server, die Seite entfernt es sofort aus Adresszeile und Verlauf und sendet es nur im
 * Request-Body.
 *
 * Einladung = Erstlogin in drei Schritten (Design «hocX Erstlogin Einladung»): Passwort → zweiter
 * Faktor → Fertig. Nach dem Passwort liefert das Backend ein Login-Ticket (nur im Body); mit dem
 * bestätigten Faktor bzw. dem erlaubten «Später einrichten» ist die Person direkt angemeldet. Ob
 * der Faktor Pflicht ist, entscheidet das Backend (`mfa.required`, account_requires_mfa).
 * Passwortstärke: lib/password-strength.ts, dieselbe Regel prüft das Backend. Zusätzlich prüft nur
 * das Backend, ob das Passwort aus einem Datenleck bekannt ist (`password_leaked`, SEC-AUTH-015).
 */
function readTokenFromFragment(): { token: string; invite: boolean } {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const token = params.get("token") ?? "";
  if (window.location.hash) {
    window.history.replaceState(null, "", window.location.pathname);
  }
  // kind=invite steht seit dem Bereichs-Audit 05 im Link: bei abgelaufener Einladung hilft
  // «Passwort vergessen» nicht (das Konto hat noch keinen Login), nur eine neue Einladung.
  return { token, invite: params.get("kind") === "invite" };
}

type Step = "loading" | "invalid" | "locked" | "password" | "factor" | "done" | "resetDone" | "inviteLogin" | "expired";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : parts[0]?.[1] ?? "")).toUpperCase();
}

export default function SetPasswordPage() {
  const t = useTranslations("auth.setPassword");
  const router = useRouter();
  const [token, setToken] = useState("");
  const [preview, setPreview] = useState<AccountLinkPreview | null>(null);
  const [step, setStep] = useState<Step>("loading");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [inviteLink, setInviteLink] = useState(false);
  const [pendingMfa, setPendingMfa] = useState<PendingMfaLogin | null>(null);
  const [result, setResult] = useState<FactorResult | null>(null);
  const [passkeysSupported, setPasskeysSupported] = useState(false);
  // Das Fragment wird beim ersten Lesen entfernt; React StrictMode (Entwicklung) führt den Effekt
  // ein zweites Mal aus - der Ref überlebt das und liefert dann dasselbe Token statt eines leeren.
  const fragmentRef = useRef<{ token: string; invite: boolean } | null>(null);

  useEffect(() => {
    // Erst im Browser: auf dem Server gibt es kein PublicKeyCredential (sonst Hydration-Unterschied)
    setPasskeysSupported(browserSupportsPasskeys());
    let cancelled = false;
    fragmentRef.current ??= readTokenFromFragment();
    const { token: fragmentToken, invite: fragmentInvite } = fragmentRef.current;
    setInviteLink(fragmentInvite);
    if (!fragmentToken) {
      setStep("invalid");
      return;
    }
    setToken(fragmentToken);
    browserApiFetch<AccountLinkPreview>("/api/auth/account-link/preview", { method: "POST", body: JSON.stringify({ token: fragmentToken }) })
      .then((loaded) => {
        if (cancelled) return;
        setPreview(loaded);
        setStep("password");
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setStep(apiErrorCode(caught) === "rate_limited" ? "locked" : "invalid");
      });
    return () => { cancelled = true; };
  }, []);

  const invite = preview ? preview.purpose === "invite" : inviteLink;
  const strength = useMemo(
    () => evaluatePassword(password, preview ? [preview.display_name, preview.email, preview.tenant_name] : []),
    [password, preview],
  );
  const mismatch = repeat.length > 0 && password !== repeat;
  const canSubmit = strength.acceptable && password === repeat && !busy;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError("");
    try {
      const completed = await browserApiFetch<AccountLinkComplete>("/api/auth/account-link/complete", { method: "POST", body: JSON.stringify({ token, password }) });
      setPassword("");
      setRepeat("");
      if (completed.purpose !== "invite") setStep("resetDone");
      else if (completed.mfa) {
        setPendingMfa(completed.mfa);
        setStep("factor");
      } else setStep("inviteLogin");
    } catch (caught) {
      const code = apiErrorCode(caught);
      if (code === "link_invalid") setStep("invalid");
      else if (code === "rate_limited") setStep("locked");
      else if (code === "password_leaked") setError(t("passwordLeaked"));
      else setError(code === "password_weak" ? t("passwordWeak") : t("failed"));
    } finally {
      setBusy(false);
    }
  }

  function factorDone(done: FactorResult) {
    setResult(done);
    setStep("done");
  }

  function goToApp() {
    const bridge = result?.session.bridge_redirect_url;
    if (bridge && attemptBridgeRedirect(bridge)) return;
    router.replace("/");
  }

  const showStepper = invite && ["password", "factor", "done"].includes(step);
  const stepIndex = step === "password" ? 0 : step === "factor" ? 1 : 3;
  const tenantName = preview?.tenant_name ?? "";
  const wide = step === "factor";

  function renderStepper() {
    const labels = [t("steps.password"), t("steps.factor"), t("steps.done")];
    return (
      <ol className="invite-stepper" aria-label={t("steps.label")}>
        {labels.map((label, index) => {
          const done = index < stepIndex;
          const active = index === stepIndex;
          return (
            <li key={label} className={`invite-stepper-item${done ? " is-done" : ""}${active ? " is-active" : ""}`} aria-current={active ? "step" : undefined}>
              <span className="invite-stepper-dot" aria-hidden="true">{done ? "✓" : index + 1}</span>
              <span className="invite-stepper-label">{label}</span>
            </li>
          );
        })}
      </ol>
    );
  }

  function renderPasswordForm() {
    if (!preview) return null;
    return (
      <form className="account-link-form" onSubmit={(event) => void submit(event)}>
        <div className="invite-step-heading">
          <h1>{invite ? t("inviteTitle") : t("resetTitle")}</h1>
          <p className="muted">
            {invite
              ? t("inviteIntro", { name: preview.display_name, tenant: preview.tenant_name })
              : t("resetIntro", { name: preview.display_name, email: preview.email })}
          </p>
        </div>
        <label className="field-stack">
          <span className="field-label">{t("emailLabel")}</span>
          <input className="input" type="email" value={preview.email} readOnly autoComplete="username" />
        </label>
        <div className="field-stack">
          <div className="invite-field-head">
            <label className="field-label" htmlFor="set-password-new">{t("passwordLabel")}</label>
            <button type="button" className="button-ghost invite-inline-toggle" onClick={() => setShowPassword((current) => !current)} aria-pressed={showPassword}>
              {showPassword ? t("hidePassword") : t("showPassword")}
            </button>
          </div>
          <input
            id="set-password-new"
            className={strength.acceptable ? "input invite-input-ok" : "input"}
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="new-password"
            required
          />
          <PasswordStrengthMeter strength={strength} />
        </div>
        <label className="field-stack">
          <span className="field-label">{t("repeatLabel")}</span>
          <input
            className={mismatch ? "input invite-input-bad" : repeat && !mismatch ? "input invite-input-ok" : "input"}
            type={showPassword ? "text" : "password"}
            value={repeat}
            onChange={(event) => setRepeat(event.target.value)}
            autoComplete="new-password"
            required
          />
          {mismatch ? <span className="field-help invite-field-error">{t("mismatch")}</span> : null}
        </label>
        {error ? <StatusBanner tone="error" message={error} /> : null}
        <button type="submit" className="button-primary invite-submit" disabled={!canSubmit}>
          {busy ? t("saving") : invite ? t("inviteSubmit") : t("resetSubmit")}
        </button>
        <p className="muted invite-footnote">{invite ? t("nextFactorHint") : t("mfaHint")}</p>
      </form>
    );
  }

  function renderDone() {
    if (!result || !preview) return null;
    const factorText =
      result.factor === "webauthn"
        ? result.label ? t("done.factorPasskeyNamed", { label: result.label }) : t("done.factorPasskey")
        : result.factor === "totp"
          ? result.label ? t("done.factorTotpNamed", { label: result.label }) : t("done.factorTotp")
          : t("done.factorNone");
    return (
      <div className="invite-step">
        <div className="invite-done-icon" aria-hidden="true">✓</div>
        <div className="invite-step-heading">
          <h1>{t("done.title")}</h1>
          <p className="muted">{t.rich("done.signedInAs", { email: preview.email, strong: (chunks) => <strong>{chunks}</strong> })}</p>
        </div>
        <dl className="invite-summary">
          <div className="invite-summary-row">
            <dt>{t("done.password")}</dt>
            <dd><span className="invite-summary-dot is-ok" aria-hidden="true" />{t("done.passwordSet")}</dd>
          </div>
          <div className="invite-summary-row">
            <dt>{t("done.factor")}</dt>
            <dd><span className={result.factor ? "invite-summary-dot is-ok" : "invite-summary-dot is-open"} aria-hidden="true" />{factorText}</dd>
          </div>
        </dl>
        {result.factor ? null : <p className="muted invite-footnote">{t("done.recommendLater")}</p>}
        <button type="button" className="button-primary invite-submit" onClick={goToApp}>{t("done.toApp")}</button>
      </div>
    );
  }

  function renderMessage(title: string, message: string, actions: React.ReactNode) {
    return (
      <div className="invite-step">
        <div className="invite-step-heading">
          <h1>{title}</h1>
          <p className="muted" role="alert">{message}</p>
        </div>
        <div className="invite-actions">{actions}</div>
      </div>
    );
  }

  const toLogin = <a className="button-primary invite-submit" href="/login">{t("toLogin")}</a>;

  function renderStep() {
    switch (step) {
      case "loading":
        return <p className="muted invite-footnote">{t("loading")}</p>;
      case "invalid":
        return renderMessage(
          invite ? t("invalidInviteTitle") : t("invalidTitle"),
          invite ? t("inviteInvalid") : t("invalid"),
          <>
            {invite ? null : <a className="button-ghost" href="/auth/forgot-password">{t("requestNew")}</a>}
            {toLogin}
          </>,
        );
      case "locked":
        return renderMessage(t("lockedTitle"), t("rateLimited"), toLogin);
      case "password":
        return renderPasswordForm();
      case "factor":
        return pendingMfa ? (
          <InviteFactorStep
            pending={pendingMfa}
            tenantName={tenantName}
            passkeysSupported={passkeysSupported}
            onDone={factorDone}
            onExpired={() => setStep("expired")}
          />
        ) : null;
      case "done":
        return renderDone();
      case "resetDone":
        return renderMessage(t("resetTitle"), t("resetDone"), toLogin);
      case "inviteLogin":
        return renderMessage(t("inviteTitle"), t("inviteDone"), toLogin);
      case "expired":
        return renderMessage(t("expiredTitle"), t("flowExpired"), toLogin);
    }
  }

  return (
    <main className="login-frame">
      <section className={wide ? "login-panel invite-panel invite-panel-wide" : "login-panel invite-panel"}>
        {tenantName && ["password", "factor", "invalid", "locked"].includes(step) && invite ? (
          <div className="invite-brand">
            <span className="invite-brand-mark" aria-hidden="true">{initials(tenantName)}</span>
            <span className="invite-brand-name">{tenantName}</span>
          </div>
        ) : null}
        {showStepper ? renderStepper() : null}
        {renderStep()}
      </section>
    </main>
  );
}
