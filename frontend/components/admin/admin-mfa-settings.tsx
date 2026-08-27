"use client";

import { useState } from "react";

import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { TotpEnrollmentStart, UserMfaOverview } from "@/types/api";

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
  const [busy, setBusy] = useState(false);

  async function startTotp() {
    setBusy(true);
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
      setBusy(false);
    }
  }

  async function completeTotp() {
    if (!totpSetup) return;
    setBusy(true);
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
      setBusy(false);
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

  return (
    <section className="card">
      <div className="eyebrow">Zwei-Faktor-Authentifizierung</div>
      <p className="muted">
        Platform-Admin-Konten haben systemweiten Zugriff auf alle Mandanten und benötigen deshalb zwingend einen
        zweiten Faktor per Authenticator-App. Mindestens ein Faktor muss immer erhalten bleiben.
      </p>

      <div className="security-summary-card">
        <div>
          <div className="eyebrow">Sicherheitsstatus</div>
          <strong>{overview.has_factors ? "MFA ist aktiv" : "Noch kein Faktor eingerichtet"}</strong>
          <div className="muted">Für Platform-Admin-Konten ist MFA verpflichtend.</div>
        </div>
        <div className="status-row">
          <span className="pill">{overview.factors.length} Faktor(en)</span>
        </div>
      </div>

      <div className="grid">
        <div className="field-label">Neuen Faktor hinzufügen</div>
        {!totpSetup ? (
          <button type="button" className="button-inline" disabled={busy} onClick={() => void startTotp()}>
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
              <button type="button" className="button-inline" disabled={totpCode.length !== 6 || busy} onClick={() => void completeTotp()}>
                {busy ? "Wird bestätigt…" : "TOTP aktivieren"}
              </button>
              <button type="button" className="button-inline button-ghost" onClick={() => setTotpSetup(null)}>
                Abbrechen
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="grid">
        <div className="field-label">Aktive Faktoren</div>
        <div className="security-factor-list">
          {!overview.factors.length ? <div className="selection-card muted">Noch keine MFA-Faktoren eingerichtet.</div> : null}
          {overview.factors.map((factor) => {
            const isLastFactor = overview.factors.length <= 1;
            return (
              <article key={factor.id} className="security-factor-card">
                <div className="security-factor-main">
                  <div className="security-factor-row">
                    <strong>{factor.label}</strong>
                    <span className="pill">TOTP</span>
                  </div>
                  <div className="muted">Eingerichtet: {formatDate(factor.created_at)}</div>
                  <div className="muted">Zuletzt verwendet: {formatDate(factor.last_used_at)}</div>
                  {isLastFactor && <div className="muted">Letzter Faktor kann nicht entfernt werden.</div>}
                </div>
                <button
                  type="button"
                  className="button-inline button-danger"
                  disabled={isLastFactor}
                  title={isLastFactor ? "Platform-Administratoren müssen mindestens einen MFA-Faktor behalten" : undefined}
                  onClick={() => void deleteFactor(factor.id, factor.label)}
                >
                  Entfernen
                </button>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
