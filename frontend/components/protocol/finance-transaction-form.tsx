"use client";

// Zeile zum Erfassen einer Transaktion direkt im Protokoll-Block «Transaktionen». Die
// Transaktion wird mit dem Protokoll verknüpft (protocol_id), Datum vorbelegt mit dem
// Protokolldatum.
import { FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { DateInput } from "@/components/ui/date-input";
import { Select } from "@/components/ui/select";

type Props = {
  defaultDate: string;
  currency: string;
  onAdd: (values: { transaction_date: string; description: string; amount: number }) => Promise<boolean>;
};

export function FinanceTransactionForm({ defaultDate, currency, onAdd }: Props) {
  const t = useTranslations("protocols");
  const [date, setDate] = useState(defaultDate);
  const [description, setDescription] = useState("");
  const [direction, setDirection] = useState<"in" | "out">("in");
  const [amount, setAmount] = useState("");
  const [saving, setSaving] = useState(false);
  const value = Number(amount.replace(",", "."));
  const valid = !!date && !!description.trim() && Number.isFinite(value) && value > 0;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid || saving) return;
    setSaving(true);
    const ok = await onAdd({ transaction_date: date, description: description.trim(), amount: direction === "out" ? -value : value });
    setSaving(false);
    if (ok) {
      setDescription("");
      setAmount("");
    }
  }

  return (
    <form className="finance-proto-add" onSubmit={submit} aria-label={t("transactionAddTitle")}>
      <DateInput value={date} onChange={(next) => setDate(next)} aria-label={t("dateLabel")} />
      <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder={t("descriptionLabel")} aria-label={t("descriptionLabel")} maxLength={500} />
      <Select value={direction} onChange={(event) => setDirection(event.target.value as "in" | "out")} aria-label={t("transactionDirection")}>
        <option value="in">{t("transactionIncome")}</option>
        <option value="out">{t("transactionExpense")}</option>
      </Select>
      <input
        className="finance-proto-add-amount"
        inputMode="decimal"
        value={amount}
        onChange={(event) => setAmount(event.target.value)}
        placeholder={currency}
        aria-label={t("amountLabel")}
      />
      <button type="submit" className="button-secondary" disabled={!valid || saving}>
        {t("transactionAdd")}
      </button>
    </form>
  );
}
