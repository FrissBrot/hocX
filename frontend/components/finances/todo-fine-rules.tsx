"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchableMultiSelect } from "@/components/ui/searchable-select";
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
        <ModalSaveForm className="grid" onSubmit={submit}>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("todoFines.ruleName")}</span>
              <input value={draft.name} maxLength={120} autoFocus onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("todoFines.appliesFrom")}</span>
              <DateInput value={draft.applies_from} onChange={(value) => setDraft({ ...draft, applies_from: value })} />
              <span className="field-help">{t("todoFines.appliesFromHelp")}</span>
            </label>
          </div>
          <label className="checkbox-row">
            <input type="checkbox" checked={draft.is_active} onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })} />
            <span>{t("todoFines.activeLabel")}</span>
          </label>

          <h3 className="section-title">{t("todoFines.filterTitle")}</h3>
          <p className="muted">{t("todoFines.filterHelp")}</p>
          <div className="two-col">
            <div className="field-stack">
              <span className="field-label">{t("todoFines.filterTags")}</span>
              <SearchableMultiSelect options={tagOptions} getId={(tag) => tag} getLabel={(tag) => tag} values={draft.tags}
                emptySelectionLabel={t("todoFines.filterAny")} onChange={(tags) => setDraft({ ...draft, tags })} />
            </div>
            <div className="field-stack">
              <span className="field-label">{t("todoFines.filterPackages")}</span>
              <SearchableMultiSelect options={options?.task_packages ?? []} getId={(item) => item.id} getLabel={(item) => item.name ?? "—"}
                values={draft.task_package_ids} emptySelectionLabel={t("todoFines.filterAny")} onChange={(ids) => setDraft({ ...draft, task_package_ids: ids })} />
            </div>
            <div className="field-stack">
              <span className="field-label">{t("todoFines.filterPeople")}</span>
              <SearchableMultiSelect options={options?.participants ?? []} getId={(item) => item.id} getLabel={(item) => item.name ?? "—"}
                values={draft.participant_ids} emptySelectionLabel={t("todoFines.filterAny")} onChange={(ids) => setDraft({ ...draft, participant_ids: ids })} />
            </div>
            <div className="field-stack">
              <span className="field-label">{t("todoFines.filterRoles")}</span>
              <SearchableMultiSelect options={options?.roles ?? []} getId={(item) => item.id} getLabel={roleLabel}
                values={draft.role_ids} emptySelectionLabel={t("todoFines.filterAny")} onChange={(ids) => setDraft({ ...draft, role_ids: ids })} />
            </div>
          </div>

          <h3 className="section-title">{t("todoFines.amountTitle")}</h3>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("todoFines.intervalLabel")}</span>
              <input type="number" min={1} max={365} step={1} value={draft.interval_days} onChange={(event) => setDraft({ ...draft, interval_days: event.target.value })} />
              <span className="field-help">{t("todoFines.intervalHelp", { count: intervalDays })}</span>
            </label>
            <label className="field-stack">
              <span className="field-label">{t("todoFines.splitLabel")}</span>
              <Select value={draft.split_mode} onChange={(event) => setDraft({ ...draft, split_mode: event.target.value as FineSplitMode })}>
                <option value="each">{t("todoFines.split.each")}</option>
                <option value="split">{t("todoFines.split.split")}</option>
              </Select>
              <span className="field-help">{t("todoFines.splitHelp")}</span>
            </label>
            <label className="field-stack">
              <span className="field-label">{t("todoFines.colAccount")}</span>
              <Select value={draft.account_id} onChange={(event) => setDraft({ ...draft, account_id: event.target.value })}>
                <option value="">{t("todoFines.defaultAccount")}</option>
                {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
              </Select>
            </label>
          </div>
          <DataTable columns={[t("todoFines.colTariff"), t("todoFines.baseAmount"), t("todoFines.intervalAmount", { count: intervalDays }), t("todoFines.preview")]}>
            {tariffs.map((tariff) => {
              const rate = draft.rates[tariff.id] ?? { base: "", interval: "" };
              const set = (patch: Partial<RateDraft>) => setDraft({ ...draft, rates: { ...draft.rates, [tariff.id]: { ...rate, ...patch } } });
              return (
                <tr key={tariff.id}>
                  <td><strong>{tariff.name}</strong></td>
                  <td><input type="number" min={0} step="0.05" inputMode="decimal" aria-label={t("todoFines.baseAmount")} value={rate.base} onChange={(event) => set({ base: event.target.value })} /></td>
                  <td><input type="number" min={0} step="0.05" inputMode="decimal" aria-label={t("todoFines.intervalAmount", { count: intervalDays })} value={rate.interval} onChange={(event) => set({ interval: event.target.value })} /></td>
                  <td className="muted">
                    {PREVIEW_DAYS.map((days) => t("todoFines.previewItem", { count: days, amount: ruleAmount(amountOf(rate.base), amountOf(rate.interval), intervalDays, days).toFixed(2) })).join(" · ")}
                  </td>
                </tr>
              );
            })}
          </DataTable>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setEditing(null)}>{tCommon("cancel")}</button>
            <button data-modal-save type="submit" className="button-primary" disabled={!draft.name.trim() || !draft.applies_from || saving}>{tCommon("save")}</button>
          </div>
        </ModalSaveForm>
      </Modal>
    </div>
  );
}
