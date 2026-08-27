"use client";

import { useEffect, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { UserMfaOverview } from "@/types/api";

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
  onClose: () => void;
  title: string;
  loadPath: string | null;
  deletePathBase: string | null;
};

export function MfaAdminModal({ open, onClose, title, loadPath, deletePathBase }: Props) {
  const confirm = useConfirm();
  const showToast = useToast();
  const [overview, setOverview] = useState<UserMfaOverview | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !loadPath) {
      return;
    }
    setLoading(true);
    browserApiFetch<UserMfaOverview>(loadPath)
      .then((result) => setOverview(result))
      .catch((error) => {
        showToast(error instanceof Error ? error.message : "MFA-Daten konnten nicht geladen werden", "error");
      })
      .finally(() => setLoading(false));
  }, [loadPath, open, showToast]);

  async function deleteFactor(factorId: string, label: string) {
    if (!deletePathBase) return;
    const ok = await confirm({
      message: `MFA-Faktor "${label}" wirklich löschen? Der Benutzer muss ihn danach neu einrichten.`,
      tone: "danger",
      confirmLabel: "Jetzt löschen",
    });
    if (!ok) return;
    try {
      const next = await browserApiFetch<UserMfaOverview>(`${deletePathBase}/${factorId}`, {
        method: "DELETE",
      });
      setOverview(next);
      showToast("MFA-Faktor gelöscht", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "MFA-Faktor konnte nicht gelöscht werden", "error");
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      description="Alle hinterlegten zweiten Faktoren dieses Kontos. Löschen entspricht einem Reset der jeweiligen Option."
      size="wide"
    >
      <div className="grid">
        <div className="security-summary-card">
          <div>
            <div className="eyebrow">Status</div>
            <strong>{overview?.required ? "MFA ist für dieses Konto Pflicht" : "MFA ist für dieses Konto optional"}</strong>
            <div className="muted">
              {loading ? "Lädt…" : overview?.has_factors ? `${overview.factors.length} Faktor(en) hinterlegt` : "Noch keine Faktoren eingerichtet"}
            </div>
            {overview?.preferred_factor_type ? (
              <div className="muted">Standardmethode: {factorTypeLabel(overview.preferred_factor_type)}</div>
            ) : null}
          </div>
        </div>

        <div className="security-factor-list">
          {!loading && (!overview || overview.factors.length === 0) ? (
            <div className="selection-card muted">Keine MFA-Faktoren vorhanden.</div>
          ) : null}
          {overview?.factors.map((factor) => (
            <article key={factor.id} className="security-factor-card">
              <div className="security-factor-main">
                <div className="security-factor-row">
                  <strong>{factor.label}</strong>
                  <span className="pill">{factorTypeLabel(factor.factor_type)}</span>
                </div>
                <div className="muted">Eingerichtet: {formatDate(factor.created_at)}</div>
                <div className="muted">Zuletzt verwendet: {formatDate(factor.last_used_at)}</div>
              </div>
              <button
                type="button"
                className="button-inline button-danger"
                onClick={() => void deleteFactor(factor.id, factor.label)}
              >
                Löschen
              </button>
            </article>
          ))}
        </div>
      </div>
    </Modal>
  );
}
