"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { FineTariffModal } from "@/components/finances/fine-tariff-modal";
import { TodoFineRules } from "@/components/finances/todo-fine-rules";
import { TodoFineTariffs } from "@/components/finances/todo-fine-tariffs";
import { StatusBanner } from "@/components/ui/status-banner";
import { Tabs } from "@/components/ui/tabs";
import { formatMoney } from "@/lib/utils/format";
import { DocsLink } from "@/components/ui/help-popover";
import type { FinanceAccount, FineTariff, FineTariffGroup, TodoFineRule } from "@/types/api";

type Props = {
  initialTariff: FineTariff | null;
  initialTariffs: FineTariffGroup[];
  initialRules: TodoFineRule[];
  accounts: FinanceAccount[];
  canManage: boolean;
  /** Feature todo_fines: «none» blendet die Pendenzen-Regeln aus, «read_only» zeigt sie nur an. */
  todoFinesAccess: "none" | "read_only" | "full";
  /** Reiter aus der Adresse (?tab=, z. B. aus der Suche) */
  initialTab?: string;
};

const noop = async () => undefined;

/**
 * Bussen-Konfiguration (Navigation: Konfiguration): Anwesenheitsbussen des Vereins, Tarife mit
 * eigenen Beträgen je Person (Verspätung, Abwesenheit, Pendenzen-Regeln) und die Regeln der
 * Pendenzen-Bussen. Die Bussen selbst stehen gemeinsam in einer Liste unter Finanzen > Bussen.
 */
export function FineSettingsView({ initialTariff, initialTariffs, initialRules, accounts, canManage, todoFinesAccess, initialTab }: Props) {
  const t = useTranslations("finances");
  const locale = useLocale();
  const [tariff, setTariff] = useState<FineTariff | null>(initialTariff);
  const [tariffs, setTariffs] = useState(initialTariffs);
  const [rules, setRules] = useState(initialRules);
  const [tariffOpen, setTariffOpen] = useState(false);
  const [tab, setTab] = useState(
    (initialTab === "tariffs" && canManage) || (initialTab === "rules" && todoFinesAccess !== "none") ? initialTab : "attendance",
  );
  const accountName = (id: string | null) => accounts.find((account) => account.id === id)?.name ?? t("unknownAccount");
  // Währung des Bussenkontos (Beträge im Tarif sind ohne Währung gespeichert)
  const currency = accounts.find((account) => account.id === tariff?.account_id)?.currency_label ?? "";

  const attendance = (
    <div className="grid">
      <p className="muted">{t("fineSettings.attendanceDescription")}</p>
      {tariff ? (
        <div className="fine-settings-summary">
          <dl className="fine-settings-values">
            <div><dt>{t("fineSettings.account")}</dt><dd>{tariff.account_id ? accountName(tariff.account_id) : t("tariffNoAccount")}</dd></div>
            <div><dt>{t("fineSettings.amountLate")}</dt><dd className="fine-settings-amount">{formatMoney(tariff.amount_late, currency, locale)}</dd></div>
            <div><dt>{t("fineSettings.amountAbsent")}</dt><dd className="fine-settings-amount">{formatMoney(tariff.amount_absent, currency, locale)}</dd></div>
          </dl>
          {canManage ? <button type="button" className="button-secondary" onClick={() => setTariffOpen(true)}>{t("tariffButton")}</button> : null}
        </div>
      ) : null}
      {tariff && !tariff.account_id ? <StatusBanner tone="warning" message={t("tariffNotSet")} /> : null}
      <p className="field-help">
        {canManage ? (
          <>
            {t("fineSettings.attendanceHintBefore")}{" "}
            <button type="button" className="fine-settings-tab-link" onClick={() => setTab("tariffs")}>{t("fineSettings.tariffsTabLink")}</button>
            {t("fineSettings.attendanceHintAfter")}
          </>
        ) : t("fineSettings.attendanceTariffHint")}
      </p>
      {tariff ? <FineTariffModal open={tariffOpen} tariff={tariff} accounts={accounts} onClose={() => setTariffOpen(false)} onSaved={setTariff} /> : null}
    </div>
  );

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("fineSettings.pageTitle")}</h1>
          <p className="muted">
            {t("fineSettings.description")} <DocsLink page="finanzen" anchor="bussentarif">{t("docsLink")}</DocsLink>
          </p>
        </div>
      </div>
      {todoFinesAccess === "read_only" ? <StatusBanner tone="neutral" message={t("todoFines.readOnlyNotice")} /> : null}
      <Tabs
        activeId={tab}
        onChange={setTab}
        tabs={[
          { id: "attendance", label: t("fineSettings.tabAttendance"), content: attendance },
          ...(canManage
            ? [{ id: "tariffs", label: t("fineSettings.tabTariffs"), count: tariffs.length, content: <TodoFineTariffs tariffs={tariffs} setTariffs={setTariffs} canManage clubTariff={tariff} currency={currency} onChanged={noop} /> }]
            : []),
          ...(todoFinesAccess !== "none"
            ? [{
                id: "rules",
                label: t("fineSettings.tabTodoRules"),
                count: rules.length,
                content: <TodoFineRules rules={rules} setRules={setRules} tariffs={tariffs} accounts={accounts} canManage={canManage && todoFinesAccess === "full"} onChanged={noop} />,
              }]
            : []),
        ]}
      />
    </div>
  );
}
