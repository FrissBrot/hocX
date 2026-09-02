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

function sanitizeTotpCode(value: string) {
  return value.replace(/\D/g, "").slice(0, 6);
}

function factorTypeLabel(type: "totp" | "webauthn") {
  return type === "totp" ? "TOTP" : "Passkey";
}

function ShieldIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" width={24} height={24} aria-hidden="true" className={className}>
      <path d="M12 3l7 3v6c0 4.5-2.9 7.9-7 9-4.1-1.1-7-4.5-7-9V6l7-3z" />
      <path d="M9 12l2 2 4-4.2" />
    </svg>
  );
}

function KeyIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" width={20} height={20} aria-hidden="true" className={className}>
      <circle cx="7.5" cy="15.5" r="4.5" />
      <path d="M10.9 12.1L20 3" />
      <path d="M16.5 6.5L19 9" />
      <path d="M13.5 9.5L15.5 11.5" />
    </svg>
  );
}

function FingerprintIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" width={20} height={20} aria-hidden="true" className={className}>
      <path d="M12 4a8 8 0 0 0-8 8c0 2.2.4 3.9 1 5.2" />
      <path d="M12 4a8 8 0 0 1 8 8c0 1.1-.06 2-.2 2.8" />
      <path d="M8 20c-.7-1.2-1-2.6-1-4a5 5 0 0 1 10 0c0 .5-.02.9-.06 1.3" />
      <path d="M12 20.5c-1-1.4-1.5-3-1.5-4.5a1.5 1.5 0 0 1 3 0c0 1 .2 1.9.6 2.7" />
      <path d="M16 19c-.5-.8-.8-1.9-.8-3" />
    </svg>
  );
}

function TrashIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" width={16} height={16} aria-hidden="true" className={className}>
      <path d="M4 7h16" />
      <path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
      <path d="M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13" />
    </svg>
  );
}

type Props = {
  initialOverview: UserMfaOverview;
};

export function AdminMfaSettings({ initialOverview }: Props) {
  const showToast = useToast();
  const confirm = useConfirm();
  const [overview, setOverview] = useState<UserMfaOverview>(initialOverview);
  const [totpSetup, setTotpSetup] = useState<TotpEnrollmentStart | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [totpLabel, setTotpLabel] = useState("");
  const [passkeyLabel, setPasskeyLabel] = useState("");
  const [busyTotp, setBusyTotp] = useState(false);
  const [busyPasskey, setBusyPasskey] = useState(false);
  // Starts false to match server-rendered markup, then flips after mount - calling
  // browserSupportsPasskeys() directly during render would read `window` on the server too
  // (this page renders immediately, unlike MfaProfilePanel which only ever mounts inside an
  // already-open client modal) and desync the hydrated DOM from what the server sent.
  const [passkeysSupported, setPasskeysSupported] = useState(false);

  useEffect(() => {
    setPasskeysSupported(browserSupportsPasskeys());
  }, []);

  async function startTotp() {
    setBusyTotp(true);
    try {
      const result = await browserApiFetch<TotpEnrollmentStart>("/api/admin/mfa/totp/start", {
        method: "POST",
      });
      setTotpSetup(result);
      setTotpCode("");
      setTotpLabel("");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "TOTP-Setup konnte nicht gestartet werden", "error");
    } finally {
      setBusyTotp(false);
    }
  }

  async function completeTotp() {
    if (!totpSetup) return;
    setBusyTotp(true);
    try {
      const next = await browserApiFetch<UserMfaOverview>("/api/admin/mfa/totp/complete", {
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
      setBusyTotp(false);
    }
  }

  async function startPasskey() {
    if (!passkeysSupported) {
      showToast("Dieser Browser unterstützt keine Passkeys.", "error");
      return;
    }
    setBusyPasskey(true);
    try {
      const start = await browserApiFetch<PasskeyRegistrationStart>("/api/admin/mfa/passkeys/start", {
        method: "POST",
      });
      const credential = await createPasskeyCredential(start.public_key);
      const next = await browserApiFetch<UserMfaOverview>("/api/admin/mfa/passkeys/complete", {
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
      setBusyPasskey(false);
    }
  }

  async function deleteFactor(factorId: string, label: string) {
    const ok = await confirm({
      message: `MFA-Faktor "${label}" wirklich entfernen?`,
      tone: "danger",
      confirmLabel: "Entfernen",
    });
    if (!ok) return;
    try {
      const next = await browserApiFetch<UserMfaOverview>(`/api/admin/mfa/factors/${factorId}`, {
        method: "DELETE",
      });
      setOverview(next);
      showToast("MFA-Faktor entfernt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "MFA-Faktor konnte nicht entfernt werden", "error");
    }
  }

  const hasTotpFactor = overview.factors.some((factor) => factor.factor_type === "totp");
  const hasPasskeyFactor = overview.factors.some((factor) => factor.factor_type === "webauthn");

  return (
    <div className="grid">
      <div>
        <div className="eyebrow">Zwei-Faktor-Authentifizierung</div>
        <p className="muted" style={{ marginTop: 6, maxWidth: "60ch" }}>
          Platform-Admin-Konten haben systemweiten Zugriff auf alle Mandanten und benötigen deshalb zwingend einen
          zweiten Faktor. Mindestens ein Faktor muss immer erhalten bleiben.
        </p>
      </div>

      <div className="security-summary-card">
        <div className="security-hero">
          <div className={`security-hero-icon${overview.has_factors ? " is-active" : ""}`}>
            <ShieldIcon />
          </div>
          <div className="security-hero-body">
            <div className="eyebrow">Sicherheitsstatus</div>
            <div className="security-hero-title">{overview.has_factors ? "MFA ist aktiv" : "Noch kein Faktor eingerichtet"}</div>
            <div className="muted">Für Platform-Admin-Konten ist MFA verpflichtend.</div>
          </div>
        </div>
        <div className="status-row">
          <span className="pill pill-required">Pflicht</span>
          <span className="pill">{overview.factors.length} Faktor(en)</span>
          <span className="pill">{passkeysSupported ? "Passkeys verfügbar" : "Kein Passkey-Support im Browser"}</span>
        </div>
      </div>

      <div className="two-col">
        <article className="security-method-card">
          <div className="security-method-header">
            <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
              <div className="security-method-icon">
                <KeyIcon />
              </div>
              <div>
                <div className="eyebrow">Option A</div>
                <h3>Authenticator-App</h3>
              </div>
            </div>
            {hasTotpFactor ? <span className="pill">Eingerichtet</span> : null}
          </div>
          <p className="muted">
            Ein zeitbasierter Code (TOTP) aus einer Authenticator-App wie Bitwarden, 1Password oder Google
            Authenticator.
          </p>
          {!totpSetup ? (
            <button type="button" className="button-inline" disabled={busyTotp} onClick={() => void startTotp()}>
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
                <input value={totpLabel} onChange={(event) => setTotpLabel(event.target.value)} placeholder="z.B. Diensthandy" />
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
              <div className="table-actions table-actions-start">
                <button type="button" className="button-inline" disabled={totpCode.length !== 6 || busyTotp} onClick={() => void completeTotp()}>
                  {busyTotp ? "Wird bestätigt…" : "TOTP aktivieren"}
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
            <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
              <div className="security-method-icon">
                <FingerprintIcon />
              </div>
              <div>
                <div className="eyebrow">Option B</div>
                <h3>Passkey</h3>
              </div>
            </div>
            {hasPasskeyFactor ? <span className="pill">Eingerichtet</span> : null}
          </div>
          <p className="muted">
            Entsperrung über Face ID, Touch ID, Windows Hello oder einen Sicherheitsschlüssel - schnell und ohne
            Code abtippen.
          </p>
          {passkeysSupported ? (
            <div className="grid">
              <label className="field-stack">
                <span className="field-label">Bezeichnung</span>
                <input
                  value={passkeyLabel}
                  onChange={(event) => setPasskeyLabel(event.target.value)}
                  placeholder="z.B. YubiKey / MacBook Pro"
                />
              </label>
              <button type="button" className="button-inline" disabled={busyPasskey} onClick={() => void startPasskey()}>
                {busyPasskey ? "Passkey wird vorbereitet…" : "Passkey hinzufügen"}
              </button>
            </div>
          ) : (
            <div className="info-note">Dieser Browser unterstützt keine Passkeys.</div>
          )}
        </article>
      </div>

      <div className="grid">
        <div className="field-label">Aktive Faktoren</div>
        <div className="security-factor-list">
          {!overview.factors.length ? <div className="selection-card muted">Noch keine MFA-Faktoren eingerichtet.</div> : null}
          {overview.factors.map((factor) => {
            const isLastFactor = overview.factors.length <= 1;
            const isWebauthn = factor.factor_type === "webauthn";
            return (
              <article key={factor.id} className="security-factor-card">
                <div className="security-factor-row-main">
                  <div className={`security-factor-icon${isWebauthn ? " is-webauthn" : ""}`}>
                    {isWebauthn ? <FingerprintIcon /> : <KeyIcon />}
                  </div>
                  <div className="security-factor-main">
                    <div className="security-factor-row">
                      <strong>{factor.label}</strong>
                      <span className="pill">{factorTypeLabel(factor.factor_type)}</span>
                    </div>
                    <div className="muted">Eingerichtet: {formatDate(factor.created_at)}</div>
                    <div className="muted">Zuletzt verwendet: {formatDate(factor.last_used_at)}</div>
                    {isLastFactor && <div className="muted">Letzter Faktor kann nicht entfernt werden.</div>}
                  </div>
                </div>
                <button
                  type="button"
                  className="button-inline button-danger"
                  disabled={isLastFactor}
                  title={isLastFactor ? "Platform-Administratoren müssen mindestens einen MFA-Faktor behalten" : undefined}
                  onClick={() => void deleteFactor(factor.id, factor.label)}
                >
                  <TrashIcon />
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
