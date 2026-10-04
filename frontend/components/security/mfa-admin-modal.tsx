"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { formatMfaDate, mfaFactorTypeLabel } from "@/lib/hooks/use-mfa-enrollment";
import type { Locale } from "@/i18n/locale-config.generated";
import { UserMfaOverview } from "@/types/api";

type Props = {
  open: boolean;
  onClose: () => void;
  title: string;
  loadPath: string | null;
  deletePathBase: string | null;
};

export function MfaAdminModal({ open, onClose, title, loadPath, deletePathBase }: Props) {
  const t = useTranslations("security.mfaAdminModal");
  const locale = useLocale() as Locale;
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
        showToast(error instanceof Error ? error.message : t("loadFailed"), "error");
      })
      .finally(() => setLoading(false));
  }, [loadPath, open, showToast, t]);

  async function deleteFactor(factorId: string, label: string) {
    if (!deletePathBase) return;
    const ok = await confirm({
      message: t("deleteConfirm", { label }),
      tone: "danger",
      confirmLabel: t("deleteNow"),
    });
    if (!ok) return;
    try {
      const next = await browserApiFetch<UserMfaOverview>(`${deletePathBase}/${factorId}`, {
        method: "DELETE",
      });
      setOverview(next);
      showToast(t("factorDeleted"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("factorDeleteFailed"), "error");
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      description={t("description")}
      size="wide"
    >
      <div className="grid">
        <div className="security-summary-card">
          <div>
            <div className="eyebrow">{t("status")}</div>
            <strong>{overview?.required ? t("mandatory") : t("optional")}</strong>
            <div className="muted">
              {loading ? t("loading") : overview?.has_factors ? t("factorCount", { count: overview.factors.length }) : t("noFactorsYet")}
            </div>
            {overview?.preferred_factor_type ? (
              <div className="muted">{t("defaultMethod", { method: mfaFactorTypeLabel(overview.preferred_factor_type) })}</div>
            ) : null}
          </div>
        </div>

        <div className="security-factor-list">
          {!loading && (!overview || overview.factors.length === 0) ? (
            <div className="selection-card muted">{t("noFactors")}</div>
          ) : null}
          {overview?.factors.map((factor) => (
            <article key={factor.id} className="security-factor-card">
              <div className="security-factor-main">
                <div className="security-factor-row">
                  <strong>{factor.label}</strong>
                  <span className="pill">{mfaFactorTypeLabel(factor.factor_type)}</span>
                </div>
                <div className="muted">{t("setUpAt", { date: formatMfaDate(factor.created_at, locale) })}</div>
                <div className="muted">{t("lastUsedAt", { date: formatMfaDate(factor.last_used_at, locale) })}</div>
              </div>
              <button
                type="button"
                className="button-secondary button-danger"
                onClick={() => void deleteFactor(factor.id, factor.label)}
              >
                {t("delete")}
              </button>
            </article>
          ))}
        </div>
      </div>
    </Modal>
  );
}
