"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Select } from "@/components/ui/select";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { localIsoDate } from "@/lib/documents/todo-export-filter";
import { formatDate } from "@/lib/utils/format";
import type { FinanceAccount, FineSplitMode, FineTariffGroup, TodoFineRule } from "@/types/api";

type Option = { id: string; name: string | null; system_key?: string | null };
type FilterOptions = { tags: string[]; task_packages: Option[]; roles: Option[]; participants: Option[] };
type RateDraft = { base: string; interval: string };
type Draft = {
  name: string;
  is_active: boolean;
  applies_from: string;
  interval_days: string;
  split_mode: FineSplitMode;
  account_id: string;
  tags: string[];
  task_package_ids: string[];
  participant_ids: string[];
  role_ids: string[];
  rates: Record<string, RateDraft>;
};

/** Betrag einer Regel nach `days` Tagen Verspätung - dieselbe Formel wie todo_fine_service.rule_amount. */
export function ruleAmount(base: number, perInterval: number, intervalDays: number, days: number): number {
  if (days < 1) return 0;
  return Math.round((base + Math.floor(days / Math.max(intervalDays, 1)) * perInterval) * 100) / 100;
}

const PREVIEW_DAYS = [1, 3, 7, 14];

function toDraft(rule: TodoFineRule | null, tariffs: FineTariffGroup[]): Draft {
  const rates: Record<string, RateDraft> = {};
  for (const tariff of tariffs) {
    const rate = rule?.rates.find((item) => item.tariff_group_id === tariff.id);
    rates[tariff.id] = { base: rate ? String(rate.base_amount) : "", interval: rate ? String(rate.interval_amount) : "" };
  }
  return {
    name: rule?.name ?? "",
    is_active: rule?.is_active ?? true,
    applies_from: rule?.applies_from ?? localIsoDate(),
    interval_days: String(rule?.interval_days ?? 1),
    split_mode: rule?.split_mode ?? "each",
    account_id: rule?.account_id ?? "",
    tags: rule?.filter.tags ?? [],
    task_package_ids: rule?.filter.task_package_ids ?? [],
    participant_ids: rule?.filter.participant_ids ?? [],
    role_ids: rule?.filter.role_ids ?? [],
    rates,
  };
}

function amountOf(value: string): number {
  const parsed = Number(value.replace(",", "."));
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

/** Regeln der Pendenzen-Bussen: Filter, Intervall, Aufteilung und Beträge je Tarif. */
export function TodoFineRules({ rules, setRules, tariffs, accounts, canManage, onChanged }: {
  rules: TodoFineRule[];
  setRules: (rules: TodoFineRule[]) => void;
  tariffs: FineTariffGroup[];
  accounts: FinanceAccount[];
  canManage: boolean;
  onChanged: () => Promise<void>;
}) {
  const t = useTranslations("finances");
  const tCommon = useTranslations("common");
  const tNav = useTranslations("nav");
  const confirm = useConfirm();
  const showToast = useToast();
  const [editing, setEditing] = useState<TodoFineRule | "new" | null>(null);
  const [draft, setDraft] = useState<Draft>(() => toDraft(null, tariffs));
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [saving, setSaving] = useState(false);
  const accountName = useMemo(() => new Map(accounts.map((account) => [account.id, account.name])), [accounts]);

  useEffect(() => {
    if (editing === null || options !== null || !canManage) return;
    browserApiFetch<FilterOptions>("/api/todo-fines/filter-options")
      .then(setOptions)
      .catch((error) => showToast(error instanceof Error ? error.message : t("todoFines.loadFailed"), "error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing]);

  const roleLabel = (role: Option) => role.name || (role.system_key ? tNav(`roles.${role.system_key}`) : "—");
  const tagOptions = useMemo(() => Array.from(new Set([...(options?.tags ?? []), ...draft.tags])), [options, draft.tags]);

  function open(rule: TodoFineRule | "new") {
    setEditing(rule);
    setDraft(toDraft(rule === "new" ? null : rule, tariffs));
  }

  async function reloadRules() {
    setRules(await browserApiFetch<TodoFineRule[]>("/api/todo-fines/rules"));
    await onChanged();
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing || !draft.name.trim()) return;
    setSaving(true);
    try {
      await browserApiFetch(editing === "new" ? "/api/todo-fines/rules" : `/api/todo-fines/rules/${editing.id}`, {
        method: editing === "new" ? "POST" : "PUT",
        body: JSON.stringify({
          name: draft.name.trim(),
          is_active: draft.is_active,
          applies_from: draft.applies_from,
          interval_days: Math.max(1, Math.min(365, Math.round(Number(draft.interval_days) || 1))),
          split_mode: draft.split_mode,
          account_id: draft.account_id || null,
          filter: { tags: draft.tags, task_package_ids: draft.task_package_ids, participant_ids: draft.participant_ids, role_ids: draft.role_ids },
          rates: tariffs.map((tariff) => ({
            tariff_group_id: tariff.id,
            base_amount: amountOf(draft.rates[tariff.id]?.base ?? ""),
            interval_amount: amountOf(draft.rates[tariff.id]?.interval ?? ""),
          })),
        }),
      });
      await reloadRules();
      setEditing(null);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("todoFines.saveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  async function remove(rule: TodoFineRule) {
    if (!await confirm({ message: t("todoFines.ruleDeleteConfirm", { name: rule.name }), tone: "danger", confirmLabel: tCommon("delete") })) return;
    try {
      await browserApiFetch(`/api/todo-fines/rules/${rule.id}`, { method: "DELETE" });
      await reloadRules();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("todoFines.saveFailed"), "error");
    }
  }

  async function move(rule: TodoFineRule, delta: number) {
    const index = rules.findIndex((item) => item.id === rule.id);
    const target = index + delta;
    if (target < 0 || target >= rules.length) return;
    const ordered = [...rules];
    [ordered[index], ordered[target]] = [ordered[target], ordered[index]];
    setRules(ordered);
    try {
      await browserApiFetch("/api/todo-fines/rules/order", { method: "PUT", body: JSON.stringify({ ids: ordered.map((item) => item.id) }) });
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("todoFines.saveFailed"), "error");
    }
  }

  function filterSummary(rule: TodoFineRule): string {
    const parts: string[] = [];
    if (rule.filter.tags.length) parts.push(t("todoFines.filterSummaryTags", { tags: rule.filter.tags.join(", ") }));
    if (rule.filter.task_package_ids.length) parts.push(t("todoFines.filterSummaryPackages", { count: rule.filter.task_package_ids.length }));
    if (rule.filter.participant_ids.length) parts.push(t("todoFines.filterSummaryPeople", { count: rule.filter.participant_ids.length }));
    if (rule.filter.role_ids.length) parts.push(t("todoFines.filterSummaryRoles", { count: rule.filter.role_ids.length }));
    return parts.length ? parts.join(" · ") : t("todoFines.filterSummaryAll");
  }

  const intervalDays = Math.max(1, Math.round(Number(draft.interval_days) || 1));
  const currency = accounts.find((account) => account.id === draft.account_id)?.currency_label ?? accounts[0]?.currency_label ?? "CHF";

  // Filter als Chip-Felder (Design «Bussenregel Dialog»): leer = alle, «+ Wählen» fügt hinzu.
  type FilterKey = "tags" | "task_package_ids" | "participant_ids" | "role_ids";
  const filterSource: Record<FilterKey, { id: string; label: string }[]> = {
    tags: tagOptions.map((tag) => ({ id: tag, label: tag })),
    task_package_ids: (options?.task_packages ?? []).map((item) => ({ id: item.id, label: item.name ?? "—" })),
    participant_ids: (options?.participants ?? []).map((item) => ({ id: item.id, label: item.name ?? "—" })),
    role_ids: (options?.roles ?? []).map((item) => ({ id: item.id, label: roleLabel(item) })),
  };
  const filterLabels: Record<FilterKey, string> = {
    tags: t("todoFines.filterTags"),
    task_package_ids: t("todoFines.filterPackages"),
    participant_ids: t("todoFines.filterPeople"),
    role_ids: t("todoFines.filterRoles"),
  };
  const filterFields = (Object.keys(filterLabels) as FilterKey[]).map((key) => {
    const byId = new Map(filterSource[key].map((item) => [item.id, item]));
    return {
      key,
      label: filterLabels[key],
      selected: draft[key].map((id) => byId.get(id) ?? { id, label: key === "tags" ? id : "…" }),
      available: filterSource[key].filter((item) => !draft[key].includes(item.id)),
      add: (id: string) => setDraft((current) => ({ ...current, [key]: [...current[key], id] })),
      remove: (id: string) => setDraft((current) => ({ ...current, [key]: current[key].filter((value) => value !== id) })),
    };
  });
  const draftFilterSummary = filterSummary({ filter: { tags: draft.tags, task_package_ids: draft.task_package_ids, participant_ids: draft.participant_ids, role_ids: draft.role_ids } } as TodoFineRule);

  return (
    <div className="grid">
      <div className="todo-fine-toolbar">
        <p className="muted">{t("todoFines.rulesDescription")}</p>
        {canManage ? <button type="button" className="button-primary" disabled={tariffs.length === 0} onClick={() => open("new")}>{t("todoFines.addRule")}</button> : null}
      </div>
      {canManage && tariffs.length === 0 ? <p className="muted">{t("todoFines.needTariffFirst")}</p> : null}
      <DataTable
        columns={[t("todoFines.colRule"), t("todoFines.colFilter"), t("todoFines.colInterval"), t("todoFines.colAccount"), ...(canManage ? [tCommon("actions")] : [])]}
        emptyMessage={t("todoFines.noRules")}
      >
        {rules.map((rule, index) => (
          <tr key={rule.id} className={rule.is_active ? "" : "table-row-done"}>
            <td>
              <strong>{rule.name}</strong> {rule.is_active ? null : <Badge variant="neutral">{t("todoFines.inactive")}</Badge>}
              <div className="muted">{t("todoFines.appliesFromShort", { date: formatDate(rule.applies_from) })}</div>
            </td>
            <td>{filterSummary(rule)}</td>
            <td>
              {t("todoFines.everyDays", { count: rule.interval_days })}
              <div className="muted">{t(`todoFines.split.${rule.split_mode}`)}</div>
            </td>
            <td>{rule.account_id ? accountName.get(rule.account_id) ?? "—" : t("todoFines.defaultAccount")}</td>
            {canManage ? (
              <td>
                <div className="table-actions table-actions-start">
                  <button type="button" className="row-text-action" disabled={index === 0} onClick={() => void move(rule, -1)} aria-label={t("todoFines.moveUp")}>↑</button>
                  <button type="button" className="row-text-action" disabled={index === rules.length - 1} onClick={() => void move(rule, 1)} aria-label={t("todoFines.moveDown")}>↓</button>
                  <button type="button" className="row-text-action" onClick={() => open(rule)}>{tCommon("edit")}</button>
                  <button type="button" className="row-text-action row-text-action-danger" onClick={() => void remove(rule)}>{tCommon("delete")}</button>
                </div>
              </td>
            ) : null}
          </tr>
        ))}
      </DataTable>

      <Modal open={editing !== null} size="wide" onClose={() => setEditing(null)} title={editing === "new" ? t("todoFines.addRule") : t("todoFines.editRule")}>
        <ModalSaveForm className="fine-rule-form" onSubmit={submit}>
          <div className="fine-rule-grid">
            <label className="field-stack">
              <span className="field-label">{t("todoFines.ruleName")}</span>
              <input value={draft.name} maxLength={120} autoFocus placeholder={t("todoFines.ruleNamePlaceholder")} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("todoFines.appliesFrom")}</span>
              <DateInput value={draft.applies_from} onChange={(value) => setDraft({ ...draft, applies_from: value })} />
              <span className="field-help">{t("todoFines.appliesFromHelp")}</span>
            </label>
          </div>

          <section className="fine-rule-section">
            <div className="fine-rule-section-head">
              <h3>{t("todoFines.filterTitle")}</h3>
              <span className="muted">{draftFilterSummary}</span>
            </div>
            <div className="fine-rule-box">
              <div className="fine-rule-filters">
                {filterFields.map((field) => (
                  <div key={field.key} className="fine-rule-filter">
                    <span className="field-label">{field.label}</span>
                    <div className="fine-chip-field">
                      {field.selected.length === 0 ? <span className="fine-chip-empty">{t("todoFines.filterAny")}</span> : null}
                      {field.selected.map((item) => (
                        <span key={item.id} className="fine-chip">
                          {item.label}
                          <button type="button" aria-label={t("todoFines.filterRemove", { name: item.label })} onClick={() => field.remove(item.id)}>×</button>
                        </span>
                      ))}
                      {field.available.length > 0 ? (
                        <Select className="fine-chip-add" value="" aria-label={t("todoFines.filterAdd", { name: field.label })} onChange={(event) => event.target.value && field.add(event.target.value)}>
                          <option value="">{t("todoFines.filterChoose")}</option>
                          {field.available.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                        </Select>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
              <p className="field-help fine-rule-hint">{t("todoFines.filterHelp")}</p>
            </div>
          </section>

          <section className="fine-rule-section">
            <h3>{t("todoFines.amountTitle")}</h3>
            <div className="fine-rule-grid">
              <div className="field-stack">
                <span className="field-label">{t("todoFines.intervalLabel")}</span>
                <div className="fine-stepper-row">
                  <span>{t("todoFines.intervalEvery")}</span>
                  <div className="fine-stepper">
                    <button type="button" aria-label={t("todoFines.intervalLess")} disabled={intervalDays <= 1} onClick={() => setDraft({ ...draft, interval_days: String(Math.max(1, intervalDays - 1)) })}>−</button>
                    <span>{intervalDays}</span>
                    <button type="button" aria-label={t("todoFines.intervalMore")} disabled={intervalDays >= 365} onClick={() => setDraft({ ...draft, interval_days: String(Math.min(365, intervalDays + 1)) })}>+</button>
                  </div>
                  <span>{t("todoFines.intervalUnit", { count: intervalDays })}</span>
                </div>
              </div>
              <label className="field-stack">
                <span className="field-label">{t("todoFines.colAccount")}</span>
                <Select value={draft.account_id} onChange={(event) => setDraft({ ...draft, account_id: event.target.value })}>
                  <option value="">{t("todoFines.defaultAccount")}</option>
                  {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                </Select>
              </label>
            </div>
            <div className="field-stack">
              <span className="field-label">{t("todoFines.splitLabel")}</span>
              <FilterTabs<FineSplitMode>
                options={[{ value: "each", label: t("todoFines.split.each") }, { value: "split", label: t("todoFines.split.split") }]}
                value={draft.split_mode}
                onChange={(value) => setDraft({ ...draft, split_mode: value })}
              />
              <span className="field-help">{t(`todoFines.splitHint.${draft.split_mode}`)}</span>
            </div>
            <div className="fine-rate-table" role="table" aria-label={t("todoFines.amountTitle")}>
              <div className="fine-rate-row fine-rate-head" role="row">
                <span role="columnheader">{t("todoFines.colTariff")}</span>
                <span role="columnheader">{t("todoFines.baseAmount")}</span>
                <span role="columnheader">{t("todoFines.intervalAmount", { count: intervalDays })}</span>
                <span role="columnheader">{t("todoFines.preview")}</span>
              </div>
              {tariffs.map((tariff) => {
                const rate = draft.rates[tariff.id] ?? { base: "", interval: "" };
                const set = (patch: Partial<RateDraft>) => setDraft({ ...draft, rates: { ...draft.rates, [tariff.id]: { ...rate, ...patch } } });
                const empty = !rate.base && !rate.interval;
                return (
                  <div key={tariff.id} className="fine-rate-row" role="row">
                    <div role="cell">
                      <div className="fine-rate-name">{tariff.name} {tariff.is_default ? <Badge variant="info">{t("todoFines.defaultTariff")}</Badge> : null}</div>
                      <div className="muted fine-rate-count">{t("todoFines.tariffPeople", { count: tariff.member_count })}</div>
                    </div>
                    <label className="fine-money" role="cell">
                      <span>{currency}</span>
                      <input type="number" min={0} step="0.50" inputMode="decimal" placeholder="0.00" aria-label={t("todoFines.baseAmount")} value={rate.base} onChange={(event) => set({ base: event.target.value })} />
                    </label>
                    <label className="fine-money" role="cell">
                      <span>+</span>
                      <input type="number" min={0} step="0.50" inputMode="decimal" placeholder="0.00" aria-label={t("todoFines.intervalAmount", { count: intervalDays })} value={rate.interval} onChange={(event) => set({ interval: event.target.value })} />
                    </label>
                    <div className="fine-rate-preview" role="cell">
                      {PREVIEW_DAYS.map((days) => (
                        <div key={days}>
                          <span>{t("todoFines.previewDays", { count: days })}</span>
                          <strong>{empty ? "–" : ruleAmount(amountOf(rate.base), amountOf(rate.interval), intervalDays, days).toFixed(2)}</strong>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <div className="modal-actions fine-rule-footer">
            <label className="fine-rule-active">
              <input type="checkbox" role="switch" checked={draft.is_active} onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })} />
              <span className="album-picker-switch-track" aria-hidden="true" />
              <span className="fine-rule-active-text">
                <strong>{draft.is_active ? t("todoFines.activeOn") : t("todoFines.activeOff")}</strong>
                <span className="field-help">{draft.is_active ? t("todoFines.activeOnHint") : t("todoFines.activeOffHint")}</span>
              </span>
            </label>
            <button type="button" className="button-ghost" onClick={() => setEditing(null)}>{tCommon("cancel")}</button>
            <button data-modal-save type="submit" className="button-primary" disabled={!draft.name.trim() || !draft.applies_from || saving}>{t("todoFines.saveRule")}</button>
          </div>
        </ModalSaveForm>
      </Modal>
    </div>
  );
}
