"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { browserApiFetch } from "@/lib/api/client";
import { apiErrorCode } from "@/lib/api/error-message";
import type { AccountLinkPreview } from "@/types/api";

const MIN_PASSWORD_LENGTH = 12;

/**
 * Neues Passwort über einen Einmal-Link aus der E-Mail: «Passwort vergessen» oder Einladung
 * (Benachrichtigungen Phase 3, backend/app/notifications/account.py).
 *
 * Das Token kommt im URL-Fragment (`#token=…`, SECURITY-RULES 3.2): Der Browser schickt es an
 * keinen Server, die Seite entfernt es sofort aus Adresszeile und Verlauf und sendet es nur im
 * Request-Body. Nach dem Setzen sind alle Sitzungen beendet; ein zweiter Faktor bleibt bestehen.
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

export default function SetPasswordPage() {
  const t = useTranslations("auth.setPassword");
  const [token, setToken] = useState("");
  const [preview, setPreview] = useState<AccountLinkPreview | null>(null);
  const [invalid, setInvalid] = useState(false);
  // 429 beim Prüfen des Links: der Link ist nicht ungültig, nur kurz gesperrt
  const [rateLimited, setRateLimited] = useState(false);
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [inviteLink, setInviteLink] = useState(false);
  // Das Fragment wird beim ersten Lesen entfernt; React StrictMode (Entwicklung) führt den Effekt
  // ein zweites Mal aus - der Ref überlebt das und liefert dann dasselbe Token statt eines leeren.
  const fragmentRef = useRef<{ token: string; invite: boolean } | null>(null);

  useEffect(() => {
    let cancelled = false;
    fragmentRef.current ??= readTokenFromFragment();
    const { token: fragmentToken, invite: fragmentInvite } = fragmentRef.current;
    setInviteLink(fragmentInvite);
    if (!fragmentToken) {
      setInvalid(true);
      return;
    }
    setToken(fragmentToken);
    browserApiFetch<AccountLinkPreview>("/api/auth/account-link/preview", { method: "POST", body: JSON.stringify({ token: fragmentToken }) })
      .then((loaded) => { if (!cancelled) setPreview(loaded); })
      .catch((caught: unknown) => {
        if (cancelled) return;
        if (apiErrorCode(caught) === "rate_limited") setRateLimited(true);
        else setInvalid(true);
      });
    return () => { cancelled = true; };
  }, []);

  const tooShort = Boolean(password) && password.length < MIN_PASSWORD_LENGTH;
  const mismatch = repeat.length > 0 && password !== repeat;
  const canSubmit = password.length >= MIN_PASSWORD_LENGTH && password === repeat && !busy;
  const invite = preview ? preview.purpose === "invite" : inviteLink;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError("");
    try {
      await browserApiFetch("/api/auth/account-link/complete", { method: "POST", body: JSON.stringify({ token, password }) });
      setDone(true);
    } catch (caught) {
      const code = apiErrorCode(caught);
      if (code === "link_invalid") setInvalid(true);
      else setError(code === "rate_limited" ? t("rateLimited") : t("failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-frame">
      <section className="login-panel">
        <div className="login-heading">
          <h1>{invite ? t("inviteTitle") : t("resetTitle")}</h1>
          {preview && !done ? (
            <p className="login-subtitle">
              {invite
                ? t("inviteIntro", { name: preview.display_name, tenant: preview.tenant_name, email: preview.email })
                : t("resetIntro", { name: preview.display_name, email: preview.email })}
            </p>
          ) : null}
        </div>
        {invalid ? (
          <>
            <p className="login-status" role="alert">{invite ? t("inviteInvalid") : t("invalid")}</p>
            <div className="table-actions table-actions-start">
              {invite ? null : <a className="button-ghost" href="/auth/forgot-password">{t("requestNew")}</a>}
              <a className="button-primary" href="/login">{t("toLogin")}</a>
            </div>
          </>
        ) : rateLimited ? (
          <p className="login-status" role="alert">{t("rateLimited")}</p>
        ) : done ? (
          <>
            <p className="login-status">{invite ? t("inviteDone") : t("resetDone")}</p>
            <div className="table-actions table-actions-start">
              <a className="button-primary" href="/login">{t("toLogin")}</a>
            </div>
          </>
        ) : preview ? (
          <form className="account-link-form" onSubmit={(event) => void submit(event)}>
            <label className="field-stack">
              <span className="field-label">{t("passwordLabel")}</span>
              <input className="input" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" required />
              <span className="field-help">{tooShort ? t("tooShort", { count: MIN_PASSWORD_LENGTH }) : t("passwordHelp", { count: MIN_PASSWORD_LENGTH })}</span>
            </label>
            <label className="field-stack">
              <span className="field-label">{t("repeatLabel")}</span>
              <input className="input" type="password" value={repeat} onChange={(event) => setRepeat(event.target.value)} autoComplete="new-password" required />
              {mismatch ? <span className="field-help">{t("mismatch")}</span> : null}
            </label>
            <div className="table-actions table-actions-start">
              <button type="submit" className="button-primary" disabled={!canSubmit}>{busy ? "…" : invite ? t("inviteSubmit") : t("resetSubmit")}</button>
            </div>
            {error ? <p className="login-status" role="alert">{error}</p> : null}
            {!invite ? <p className="muted">{t("mfaHint")}</p> : null}
          </form>
        ) : (
          <p className="muted">{t("loading")}</p>
        )}
      </section>
    </main>
  );
}
