"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { HelpPopover } from "@/components/ui/help-popover";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";

const API = "/api/finance-settings";
const MAX_LENGTH = 20;

/**
 * Mandant-Einstellungen → Finanzen: eine Währung für alle Konten und Bussen des Vereins
 * (tenant.finance_currency). Speichern setzt sie bei allen Konten gleich mit; Beträge werden nicht
 * umgerechnet. Nur für den angemeldeten Mandanten (die API kennt keinen Mandanten-Parameter).
 */
export function FinanceCurrencySettings({ initialCurrency }: { initialCurrency: string }) {
  const t = useTranslations("tenantSettings.finance");
  const tCommon = useTranslations("common");
  const router = useRouter();
  const showToast = useToast();
  const [saved, setSaved] = useState(initialCurrency);
  const [currency, setCurrency] = useState(initialCurrency);
  const [saving, setSaving] = useState(false);
  const value = currency.trim();
  const valid = value !== "" && value.length <= MAX_LENGTH;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid || saving || value === saved) return;
    setSaving(true);
    try {
      const result = await browserApiFetch<{ currency: string }>(API, { method: "PATCH", body: JSON.stringify({ currency: value }) });
      setSaved(result.currency);
      setCurrency(result.currency);
      showToast(t("saved", { currency: result.currency }), "success");
      router.refresh();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("saveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="card">
      <div className="eyebrow">{t("eyebrow")}</div>
      <form className="grid" onSubmit={submit}>
        <label className="field-stack">
          <span className="field-label">
            {t("currencyLabel")}{" "}
            <HelpPopover topic={t("currencyLabel")} docs={{ page: "einstellungen" }}>
              {t("currencyHelpPopover")}
            </HelpPopover>
          </span>
          <input value={currency} maxLength={MAX_LENGTH} onChange={(event) => setCurrency(event.target.value)} required />
          <span className="field-help">{t("currencyHelp")}</span>
        </label>
        <div className="table-actions table-actions-start">
          <button type="submit" className="button-primary" disabled={saving || !valid || value === saved}>
            {tCommon("save")}
          </button>
        </div>
      </form>
    </section>
  );
}
