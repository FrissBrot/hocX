"use client";

import { useLocale, useTranslations } from "next-intl";

import { formatFineTotals, type CurrencyTotal } from "@/lib/utils/fine-stats";
import { formatMoney, toIntlLocale } from "@/lib/utils/format";

import { monthLabel, type Trend } from "./statistics-model";

/** Zahlen-, Monats- und Betragsformate der Statistik in der UI-Sprache (Desktop und Mobile). */
export function useStatisticsFormat() {
  const t = useTranslations("statistics");
  const locale = useLocale();
  const intl = toIntlLocale(locale);

  const number = (value: number | null, digits: number) =>
    value === null ? "–" : new Intl.NumberFormat(intl, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
  const signed = (value: number, digits: number) =>
    new Intl.NumberFormat(intl, { minimumFractionDigits: digits, maximumFractionDigits: digits, signDisplay: "exceptZero" }).format(value).replace("-", "−");
  const money = (value: number, currency: string) => formatMoney(value, currency, locale, { currencyFirst: true });
  const signedMoney = (value: number, currency: string) => formatMoney(value, currency, locale, { currencyFirst: true, sign: true });

  return {
    number,
    signed,
    money,
    signedMoney,
    month: (month: string) => monthLabel(month, locale),
    monthYear: (month: string) => new Intl.DateTimeFormat(intl, { month: "long", year: "numeric" }).format(new Date(`${month}-01T12:00:00`)),
    /** «Jan – Nov 2025» */
    period: (startMonth: string, endMonth: string) =>
      t("periodRange", { from: monthLabel(startMonth, locale), to: monthLabel(endMonth, locale), year: endMonth.slice(0, 4) }),
    fineTotals: (totals: CurrencyTotal[]) => formatFineTotals(totals, (amount) => formatMoney(amount, "", locale)),
    delta: ({ trend, good }: { trend: Trend; good: boolean }, text: string) => ({ text, good, flat: trend === "flat" }),
  };
}
