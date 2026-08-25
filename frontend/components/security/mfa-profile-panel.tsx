"use client";

import { useEffect, useState } from "react";

import { browserApiFetch } from "@/lib/api/client";
import { browserSupportsPasskeys, createPasskeyCredential } from "@/lib/webauthn";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { PasskeyRegistrationStart, TotpEnrollmentStart, UserMfaOverview } from "@/types/api";

function formatDate(value: string | null) {
  if (!value) return "Noch nie";
  return new Intl.DateTimeFormat("de-CH", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function factorTypeLabel(type: "totp" | "webauthn") {
  return type === "totp" ? "TOTP" : "Passkey";
}

type Props = {
  open: boolean;
};

export function MfaProfilePanel({ open }: Props) {
  const showToast = useToast();
  const confirm = useConfirm();
  const [overview, setOverview] = useState<UserMfaOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [totpSetup, setTotpSetup] = useState<TotpEnrollmentStart | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [totpLabel, setTotpLabel] = useState("");
  const [passkeyLabel, setPasskeyLabel] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    setLoading(true);
    browserApiFetch<UserMfaOverview>("/api/users/me/mfa")
      .then((result) => setOverview(result))
      .catch((error) => {
        showToast(error instanceof Error ? error.message : "MFA-Status konnte nicht geladen werden", "error");
      })
      .finally(() => setLoading(false));
  }, [open, showToast]);

  async function setPreferredMethod(factorType: "totp" | "webauthn") {
    setBusy(true);
    try {
      const next = await browserApiFetch<UserMfaOverview>("/api/users/me/mfa/preferred-method", {
        method: "PATCH",
        body: JSON.stringify({ factor_type: factorType }),
      });
      setOverview(next);
      showToast(`${factorTypeLabel(factorType)} ist jetzt die Standardmethode fürs Login`, "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Standardmethode konnte nicht gespeichert werden", "error");
    } finally {
      setBusy(false);
    }
  }

  async function startTotp() {
    try {
      const result = await browserApiFetch<TotpEnrollmentStart>("/api/users/me/mfa/totp/start", {
        method: "POST",
      });
      setTotpSetup(result);
      setTotpCode("");
      setTotpLabel("");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "TOTP-Setup konnte nicht gestartet werden", "error");
    }
  }

  async function completeTotp() {
    if (!totpSetup) return;
    setBusy(true);
    try {
      const next = await browserApiFetch<UserMfaOverview>("/api/users/me/mfa/totp/complete", {
        method: "POST",
        body: JSON.stringify({
          flow_token: totpSetup.flow_token,
          code: totpCode,
          label: totpLabel || null,
        }),
      });
      setOverview(next);
      setTotpSetup(null);
      setTotpCode("");
      setTotpLabel("");
      showToast("TOTP erfolgreich eingerichtet", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "TOTP konnte nicht bestätigt werden", "error");
    } finally {
      setBusy(false);
    }
  }

  async function startPasskey() {
    if (!browserSupportsPasskeys()) {
      showToast("Dieser Browser unterstützt keine Passkeys.", "error");
      return;
    }
    setBusy(true);
    try {
      const start = await browserApiFetch<PasskeyRegistrationStart>("/api/users/me/mfa/passkeys/start", {
        method: "POST",
      });
      const credential = await createPasskeyCredential(start.public_key);
      const next = await browserApiFetch<UserMfaOverview>("/api/users/me/mfa/passkeys/complete", {
        method: "POST",
        body: JSON.stringify({
          flow_token: start.flow_token,
          label: passkeyLabel || null,
          credential,
        }),
      });
      setOverview(next);
      setPasskeyLabel("");
      showToast("Passkey erfolgreich eingerichtet", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Passkey konnte nicht eingerichtet werden", "error");
    } finally {
      setBusy(false);
    }
  }

  async function deleteFactor(factorId: number, label: string) {
    const ok = await confirm({
      message: `MFA-Faktor "${label}" wirklich entfernen?`,
      tone: "danger",
      confirmLabel: "Entfernen",
    });
    if (!ok) return;
    try {
      const next = await browserApiFetch<UserMfaOverview>(`/api/users/me/mfa/factors/${factorId}`, {
        method: "DELETE",
      });
      setOverview(next);
      showToast("MFA-Faktor entfernt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "MFA-Faktor konnte nicht entfernt werden", "error");
    }
  }

  const hasTotpFactor = overview?.factors.some((factor) => factor.factor_type === "totp") ?? false;
  const hasPasskeyFactor = overview?.factors.some((factor) => factor.factor_type === "webauthn") ?? false;

  return (
    <div className="grid">
      <div className="security-summary-card">
        <div>
          <div className="eyebrow">Sicherheitsstatus</div>
          <strong>
            {loading
              ? "MFA wird geladen…"
              : overview?.required
                ? "Für dieses Konto ist MFA verpflichtend"
                : overview?.has_factors
                  ? "MFA ist aktiv"
                  : "MFA ist optional"}
          </strong>
          <div className="muted">
            {overview?.required
              ? "Tenant-Admins müssen mindestens einen zweiten Faktor hinterlegen."
              : "Du kannst TOTP oder einen Passkey hinterlegen. Danach wird MFA bei jedem Login abgefragt."}
          </div>
          {overview?.preferred_factor_label ? (
            <div className="muted">Standard beim Login: {overview.preferred_factor_label}</div>
          ) : null}
        </div>
        <div className="status-row">
          <span className="pill">{overview?.factors.length ?? 0} Faktor(en)</span>
          {overview?.preferred_factor_type ? <span className="pill">Standard: {factorTypeLabel(overview.preferred_factor_type)}</span> : null}
          <span className="pill">{browserSupportsPasskeys() ? "Passkeys verfügbar" : "Kein Passkey-Support im Browser"}</span>
        </div>
      </div>

      <div className="wizard-steps">
        <div className="wizard-step">
          <div className="wizard-step-dot is-done">1</div>
          <div className="wizard-step-label is-active">Methode wählen</div>
        </div>
        <div className="wizard-step-line is-done" />
        <div className="wizard-step">
          <div className={`wizard-step-dot${totpSetup ? " is-active" : overview?.has_factors ? " is-done" : ""}`}>2</div>
          <div className={`wizard-step-label${totpSetup ? " is-active" : ""}`}>Bestätigen</div>
        </div>
        <div className="wizard-step-line" />
        <div className="wizard-step">
          <div className={`wizard-step-dot${overview?.has_factors ? " is-done" : ""}`}>3</div>
          <div className="wizard-step-label">Fertig</div>
        </div>
      </div>

      <div className="two-col">
        <article className="security-method-card">
          <div className="security-method-header">
            <div>
              <div className="eyebrow">Option A</div>
              <h3>Authenticator-App mit TOTP</h3>
            </div>
            {overview?.preferred_factor_type === "totp" ? (
              <span className="pill">Login-Standard</span>
            ) : (
              <span className="pill">Universell</span>
            )}
          </div>
          <p className="muted">
            Ideal, wenn du einen zuverlässigen zweiten Faktor auf mehreren Geräten nutzen willst.
          </p>
          {hasTotpFactor && overview?.preferred_factor_type !== "totp" ? (
            <button type="button" className="button-inline button-ghost" disabled={busy} onClick={() => void setPreferredMethod("totp")}>
              Als Standard fürs Login setzen
            </button>
          ) : null}
          {!totpSetup ? (
            <button type="button" className="button-inline" onClick={() => void startTotp()}>
              TOTP einrichten
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
                <input
                  value={totpLabel}
                  onChange={(event) => setTotpLabel(event.target.value)}
                  placeholder="z.B. Diensthandy"
                />
              </label>
              <label className="field-stack">
                <span className="field-label">6-stelligen Code eingeben</span>
                <input
                  value={totpCode}
                  onChange={(event) => setTotpCode(event.target.value)}
                  inputMode="numeric"
                  placeholder="123 456"
                />
              </label>
              <div className="table-actions table-actions-start">
                <button type="button" className="button-inline" disabled={!totpCode || busy} onClick={() => void completeTotp()}>
                  {busy ? "Wird bestätigt…" : "TOTP aktivieren"}
                </button>
                <button type="button" className="button-inline button-ghost" onClick={() => setTotpSetup(null)}>
                  Abbrechen
                </button>
              </div>
            </div>
          )}
        </article>

        <article className="security-method-card">
          <div className="security-method-header">
            <div>
              <div className="eyebrow">Option B</div>
              <h3>Passkey / WebAuthn</h3>
            </div>
            {overview?.preferred_factor_type === "webauthn" ? (
              <span className="pill">Login-Standard</span>
            ) : (
              <span className="pill">Komfortabel</span>
            )}
          </div>
          <p className="muted">
            Nutzt die sichere Entsperrung deines Geräts. Perfekt für schnelle Logins mit Face ID, Touch ID oder Windows Hello.
          </p>
          {hasPasskeyFactor && overview?.preferred_factor_type !== "webauthn" ? (
            <button
              type="button"
              className="button-inline button-ghost"
              disabled={busy}
              onClick={() => void setPreferredMethod("webauthn")}
            >
              Als Standard fürs Login setzen
            </button>
          ) : null}
          {overview?.can_add_passkey_here ? (
            <div className="grid">
              <label className="field-stack">
                <span className="field-label">Bezeichnung</span>
                <input
                  value={passkeyLabel}
                  onChange={(event) => setPasskeyLabel(event.target.value)}
                  placeholder="z.B. MacBook Pro"
                />
              </label>
              <button type="button" className="button-inline" disabled={busy} onClick={() => void startPasskey()}>
                {busy ? "Passkey wird vorbereitet…" : "Passkey hinzufügen"}
              </button>
            </div>
          ) : (
            <div className="info-note">
              Passkeys können in hocX nur auf der Hauptdomain eingerichtet werden, weil Browser diese Technik fest an die Domain binden.
            </div>
          )}
        </article>
      </div>

      <div className="grid">
        <div className="field-label">Aktive Faktoren</div>
        <div className="security-factor-list">
          {!overview?.factors.length ? <div className="selection-card muted">Noch keine MFA-Faktoren eingerichtet.</div> : null}
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
                    <span className="pill">{factor.factor_type === "totp" ? "TOTP" : "Passkey"}</span>
                  </div>
                  <div className="muted">Eingerichtet: {formatDate(factor.created_at)}</div>
                  <div className="muted">Zuletzt verwendet: {formatDate(factor.last_used_at)}</div>
                  {isLastRequiredFactor && (
                    <div className="muted">Letzter Pflicht-Faktor kann nicht entfernt werden.</div>
                  )}
                </div>
                <button
                  type="button"
                  className="button-inline button-danger"
                  disabled={isLastRequiredFactor}
                  title={isLastRequiredFactor ? "Tenant-Administratoren müssen mindestens einen MFA-Faktor behalten" : undefined}
                  onClick={() => void deleteFactor(factor.id, factor.label)}
                >
                  Entfernen
                </button>
              </article>
            );
          })}
        </div>
      </div>
    </div>
  );
}
