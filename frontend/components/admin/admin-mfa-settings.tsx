"use client";

import { useEffect, useState } from "react";

import { TotpEnrollCard } from "@/components/security/totp-enroll-card";
import { useMfaEnrollment, formatMfaDate, mfaFactorTypeLabel } from "@/lib/hooks/use-mfa-enrollment";
import { browserSupportsPasskeys } from "@/lib/webauthn";
import { UserMfaOverview } from "@/types/api";

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
  const [overview, setOverview] = useState<UserMfaOverview>(initialOverview);
  const {
    totpSetup,
    setTotpSetup,
    totpCode,
    setTotpCode,
    totpLabel,
    setTotpLabel,
    passkeyLabel,
    setPasskeyLabel,
    busy,
    startTotp,
    completeTotp,
    startPasskey,
    deleteFactor,
    hasTotpFactor,
    hasPasskeyFactor,
  } = useMfaEnrollment("/api/admin/mfa", overview, setOverview);
  // Starts false to match server-rendered markup, then flips after mount - calling
  // browserSupportsPasskeys() directly during render would read `window` on the server too
  // (this page renders immediately, unlike MfaProfilePanel which only ever mounts inside an
  // already-open client modal) and desync the hydrated DOM from what the server sent.
  const [passkeysSupported, setPasskeysSupported] = useState(false);

  useEffect(() => {
    setPasskeysSupported(browserSupportsPasskeys());
  }, []);

  return (
    <div className="grid">
      <div>
        <div className="eyebrow">Zwei-Faktor-Authentifizierung</div>
        <p className="muted" style={{ marginTop: "var(--space-2)", maxWidth: "60ch" }}>
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
            <div style={{ display: "flex", gap: "var(--space-4)", alignItems: "flex-start" }}>
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
            <button type="button" className="button-secondary" disabled={busy} onClick={() => void startTotp()}>
              TOTP einrichten
            </button>
          ) : (
            <TotpEnrollCard
              setup={totpSetup}
              label={totpLabel}
              onLabelChange={setTotpLabel}
              code={totpCode}
              onCodeChange={setTotpCode}
              onSubmit={() => void completeTotp()}
              onCancel={() => setTotpSetup(null)}
              busy={busy}
            />
          )}
        </article>

        <article className="security-method-card">
          <div className="security-method-header">
            <div style={{ display: "flex", gap: "var(--space-4)", alignItems: "flex-start" }}>
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
              <button type="button" className="button-secondary" disabled={busy} onClick={() => void startPasskey()}>
                {busy ? "Passkey wird vorbereitet…" : "Passkey hinzufügen"}
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
                      <span className="pill">{mfaFactorTypeLabel(factor.factor_type)}</span>
                    </div>
                    <div className="muted">Eingerichtet: {formatMfaDate(factor.created_at)}</div>
                    <div className="muted">Zuletzt verwendet: {formatMfaDate(factor.last_used_at)}</div>
                    {isLastFactor && <div className="muted">Letzter Faktor kann nicht entfernt werden.</div>}
                  </div>
                </div>
                <button
                  type="button"
                  className="button-secondary button-danger"
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
