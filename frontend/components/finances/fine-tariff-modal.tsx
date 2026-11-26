"use client";

import { FormEvent, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { financeErrorMessage } from "@/components/finances/finance-errors";
import { MAX_FINE_TARIFF_AMOUNT, parseTariffAmount, tariffAmountValid } from "@/components/finances/fines-model";
import { formatMoney } from "@/lib/utils/format";
import { FinanceAccount, FineTariff } from "@/types/api";

type Props = {
  open: boolean;
  tariff: FineTariff;
  accounts: FinanceAccount[];
  onClose: () => void;
  onSaved: (tariff: FineTariff) => void;
};

// Zentraler Bussentarif: gilt für alle Anwesenheitsblöcke mit «Bussen aktiv». Vorher hatte jeder
// Block eigene Beträge und ein eigenes Konto (siehe Migration 0113_element_config_schema).
export function FineTariffModal({ open, tariff, accounts, onClose, onSaved }: Props) {
  const t = useTranslations("finances");
  const tCommon = useTranslations("common");
  const locale = useLocale();
  const showToast = useToast();
  const [accountId, setAccountId] = useState<string | null>(tariff.account_id);
  const [amountLate, setAmountLate] = useState(String(tariff.amount_late || ""));
  const [amountAbsent, setAmountAbsent] = useState(String(tariff.amount_absent || ""));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setAccountId(tariff.account_id);
    setAmountLate(tariff.amount_late ? String(tariff.amount_late) : "");
    setAmountAbsent(tariff.amount_absent ? String(tariff.amount_absent) : "");
  }, [open, tariff]);

  const currency = accounts.find((account) => account.id === accountId)?.currency_label ?? "";
  const parse = parseTariffAmount;
  const lateValid = tariffAmountValid(amountLate);
  const absentValid = tariffAmountValid(amountAbsent);
  const valid = lateValid && absentValid;
  const rangeHint = t("tariffAmountRange", { max: formatMoney(MAX_FINE_TARIFF_AMOUNT, "", locale) });

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid) return;
    setSaving(true);
    try {
      const saved = await browserApiFetch<FineTariff>("/api/fines/tariff", {
        method: "PUT",
        body: JSON.stringify({ account_id: accountId, amount_late: parse(amountLate), amount_absent: parse(amountAbsent) }),
      });
      onSaved(saved);
      showToast(t("tariffSaved"), "success");
      onClose();
    } catch (error) {
      showToast(financeErrorMessage(error, t, "tariffSaveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={t("tariffTitle")} description={t("tariffDescription")}>
      <ModalSaveForm className="grid" onSubmit={save}>
        <label className="field-stack">
          <span className="field-label">{t("tariffAccountLabel")}</span>
          <SearchableSelect
            options={accounts}
            getId={(account) => account.id}
            getLabel={(account) => `${account.name} (${account.currency_label})`}
            value={accountId}
            onChange={(account) => setAccountId(account ? account.id : null)}
            nullLabel={t("tariffNoAccount")}
          />
          <span className="field-help">{t("tariffAccountHelp")}</span>
        </label>
        {accountId ? null : <StatusBanner tone="warning" message={t("tariffNotSet")} />}
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">{t("tariffLateLabel")}</span>
            <span className="fine-amount-input">
              {currency ? <span className="fine-amount-currency" aria-hidden="true">{currency}</span> : null}
              <input type="number" min="0" max={MAX_FINE_TARIFF_AMOUNT} step="0.50" inputMode="decimal" value={amountLate} aria-invalid={!lateValid || undefined} onChange={(event) => setAmountLate(event.target.value)} />
            </span>
            {lateValid ? null : <span className="field-help">{rangeHint}</span>}
          </label>
          <label className="field-stack">
            <span className="field-label">{t("tariffAbsentLabel")}</span>
            <span className="fine-amount-input">
              {currency ? <span className="fine-amount-currency" aria-hidden="true">{currency}</span> : null}
              <input type="number" min="0" max={MAX_FINE_TARIFF_AMOUNT} step="0.50" inputMode="decimal" value={amountAbsent} aria-invalid={!absentValid || undefined} onChange={(event) => setAmountAbsent(event.target.value)} />
            </span>
            {absentValid ? null : <span className="field-help">{rangeHint}</span>}
          </label>
        </div>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{tCommon("cancel")}</button>
          <button data-modal-save type="submit" className="button-primary" disabled={!valid || saving}>{tCommon("save")}</button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}
