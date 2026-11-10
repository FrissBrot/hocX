"use client";

import { FormEvent, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
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

  const parse = (value: string) => Number(value.replace(",", ".") || "0");
  const valid = [amountLate, amountAbsent].every((value) => Number.isFinite(parse(value)) && parse(value) >= 0);

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
      showToast(error instanceof Error ? error.message : t("tariffSaveFailed"), "error");
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
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">{t("tariffLateLabel")}</span>
            <input type="number" min="0" step="0.50" inputMode="decimal" value={amountLate} onChange={(event) => setAmountLate(event.target.value)} />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("tariffAbsentLabel")}</span>
            <input type="number" min="0" step="0.50" inputMode="decimal" value={amountAbsent} onChange={(event) => setAmountAbsent(event.target.value)} />
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
