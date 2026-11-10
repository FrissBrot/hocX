"use client";

import { FormEvent, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { StatusBanner } from "@/components/ui/status-banner";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { FinanceAccount, TemplateFineTariff } from "@/types/api";

type Props = {
  open: boolean;
  templateId: string;
  accounts: FinanceAccount[];
  onClose: () => void;
  /** Nach dem Speichern (z. B. Anzeige «eigener Tarif» im Kopf des Vorlagen-Editors) */
  onSaved?: (tariff: TemplateFineTariff) => void;
};

// Bussentarif je Vorlage (0137, FAR-002): standardmässig gilt der Mandantentarif aus
// Finanzen > Bussen, eine Vorlage kann ihn übersteuern. Gilt sofort für alle offenen Protokolle
// der Vorlage; bereits erfasste Bussen behalten ihren Betrag.
export function TemplateFineTariffModal({ open, templateId, accounts, onClose, onSaved }: Props) {
  const t = useTranslations("templates.editor.fineTariff");
  const tFinances = useTranslations("finances");
  const tCommon = useTranslations("common");
  const showToast = useToast();
  const [loaded, setLoaded] = useState<TemplateFineTariff | null>(null);
  const [override, setOverride] = useState(false);
  const [accountId, setAccountId] = useState<string | null>(null);
  const [amountLate, setAmountLate] = useState("");
  const [amountAbsent, setAmountAbsent] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoaded(null);
    browserApiFetch<TemplateFineTariff>(`/api/templates/${templateId}/fine-tariff`)
      .then((tariff) => {
        if (cancelled) return;
        setLoaded(tariff);
        setOverride(tariff.override);
        // Ohne eigenen Tarif mit dem Mandantentarif vorbelegen - meist weicht nur ein Betrag ab.
        const source = tariff.override ? tariff : tariff.tenant_tariff;
        setAccountId(source.account_id);
        setAmountLate(source.amount_late ? String(source.amount_late) : "");
        setAmountAbsent(source.amount_absent ? String(source.amount_absent) : "");
      })
      .catch((error) => {
        if (!cancelled) showToast(error instanceof Error ? error.message : t("loadFailed"), "error");
      });
    return () => {
      cancelled = true;
    };
    // Nur beim Öffnen laden; showToast/t ändern den Request nicht.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, templateId]);

  const parse = (value: string) => Number(value.replace(",", ".") || "0");
  const valid = !override || [amountLate, amountAbsent].every((value) => Number.isFinite(parse(value)) && parse(value) >= 0);
  const accountName = (id: string | null) => (id ? accounts.find((account) => account.id === id)?.name ?? tFinances("unknownAccount") : null);
  const tenantTariff = loaded?.tenant_tariff;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid) return;
    setSaving(true);
    try {
      const saved = await browserApiFetch<TemplateFineTariff>(`/api/templates/${templateId}/fine-tariff`, {
        method: "PUT",
        body: JSON.stringify(
          override
            ? { override: true, account_id: accountId, amount_late: parse(amountLate), amount_absent: parse(amountAbsent) }
            : { override: false }
        ),
      });
      setLoaded(saved);
      onSaved?.(saved);
      showToast(t("saved"), "success");
      onClose();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("saveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={t("title")} description={t("description")}>
      <ModalSaveForm className="grid" onSubmit={save}>
        <label className="checkbox-row">
          <input type="radio" name="fine-tariff-mode" checked={!override} onChange={() => setOverride(false)} />
          <span>{t("useTenantTariff")}</span>
        </label>
        {!override && tenantTariff ? (
          <p className="field-help">
            {tenantTariff.account_id
              ? tFinances("tariffSummary", {
                  late: tenantTariff.amount_late.toFixed(2),
                  absent: tenantTariff.amount_absent.toFixed(2),
                  account: accountName(tenantTariff.account_id) ?? "",
                })
              : tFinances("tariffNotSet")}
          </p>
        ) : null}
        <label className="checkbox-row">
          <input type="radio" name="fine-tariff-mode" checked={override} onChange={() => setOverride(true)} />
          <span>{t("useOwnTariff")}</span>
        </label>
        {override ? (
          <>
            <label className="field-stack">
              <span className="field-label">{tFinances("tariffAccountLabel")}</span>
              <SearchableSelect
                options={accounts}
                getId={(account) => account.id}
                getLabel={(account) => `${account.name} (${account.currency_label})`}
                value={accountId}
                onChange={(account) => setAccountId(account ? account.id : null)}
                nullLabel={tFinances("tariffNoAccount")}
              />
              <span className="field-help">{tFinances("tariffAccountHelp")}</span>
            </label>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">{tFinances("tariffLateLabel")}</span>
                <input type="number" min="0" step="0.50" inputMode="decimal" value={amountLate} onChange={(event) => setAmountLate(event.target.value)} />
              </label>
              <label className="field-stack">
                <span className="field-label">{tFinances("tariffAbsentLabel")}</span>
                <input type="number" min="0" step="0.50" inputMode="decimal" value={amountAbsent} onChange={(event) => setAmountAbsent(event.target.value)} />
              </label>
            </div>
          </>
        ) : null}
        <StatusBanner tone="neutral" message={t("liveHint")} />
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{tCommon("cancel")}</button>
          <button data-modal-save type="submit" className="button-primary" disabled={!loaded || !valid || saving}>{tCommon("save")}</button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}
