"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { useAllPages } from "@/components/mobile/mobile-data";
import { MobileIcon } from "@/components/mobile/mobile-icons";
import { useOpenMore } from "@/components/mobile/mobile-shell";
import {
  MobileAvatar,
  MobileChip,
  MobileChipRow,
  MobileEmpty,
  MobileFab,
  MobileListRow,
  MobileSegmented,
  MobileStat,
  MobileSubHeader,
} from "@/components/mobile/mobile-ui";
import { dateParts, todayIso } from "@/components/mobile/mobile-utils";
import { FineCreateModal } from "@/components/finances/fine-create-modal";
import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { fineTypeLabels } from "@/lib/constants/fine-types";
import type { AttendanceFineListItem, FinanceAccount, FinanceTransaction } from "@/types/api";

function money(amount: number, currency?: string | null) {
  const value = new Intl.NumberFormat("de-CH", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount);
  return currency ? `${currency} ${value}` : value;
}

// ── Finanzen ────────────────────────────────────────────────────────────

type TxFilter = "all" | "income" | "expense" | "year";

export function MobileFinances({ initialAccounts, canWrite }: { initialAccounts: FinanceAccount[]; canWrite: boolean }) {
  const t = useTranslations("finances");
  const tMobile = useTranslations("mobile");
  const locale = useLocale();
  const openMore = useOpenMore();
  const confirm = useConfirm();
  const showToast = useToast();
  const [accounts, setAccounts] = useState(initialAccounts);
  const [selectedId, setSelectedId] = useState<string | null>(initialAccounts[0]?.id ?? null);
  const [transactions, setTransactions] = useState<FinanceTransaction[]>([]);
  const [filter, setFilter] = useState<TxFilter>("all");
  const [txSheet, setTxSheet] = useState<FinanceTransaction | "new" | null>(null);
  const [accountSheet, setAccountSheet] = useState<FinanceAccount | "new" | null>(null);
  const selected = accounts.find((account) => account.id === selectedId) ?? null;

  const loadTransactions = useCallback(async (accountId: string) => {
    try {
      const list: FinanceTransaction[] = [];
      for (let page = 0; page < 20; page += 1) {
        const batch = (await browserApiFetch<FinanceTransaction[]>(`/api/finance/accounts/${accountId}/transactions?skip=${list.length}&limit=200`)) ?? [];
        list.push(...batch);
        if (batch.length < 200) break;
      }
      setTransactions(list);
    } catch {
      setTransactions([]);
    }
  }, []);

  const refreshAccounts = useCallback(async () => {
    const list = (await browserApiFetch<FinanceAccount[]>("/api/finance/accounts")) ?? [];
    setAccounts(list);
    return list;
  }, []);

  useEffect(() => {
    if (selectedId) void loadTransactions(selectedId);
    else setTransactions([]);
  }, [selectedId, loadTransactions]);

  const groups = useMemo(() => {
    const year = String(new Date().getFullYear());
    const filtered = transactions.filter((tx) =>
      filter === "income" ? Math.sign(tx.amount) === 1 : filter === "expense" ? Math.sign(tx.amount) === -1 : filter === "year" ? tx.transaction_date.startsWith(year) : true
    );
    const result: { key: string; label: string; items: FinanceTransaction[] }[] = [];
    filtered.forEach((tx) => {
      const key = tx.transaction_date.slice(0, 7);
      let group = result[result.length - 1];
      if (!group || group.key !== key) {
        group = { key, label: dateParts.monthYear(tx.transaction_date, locale), items: [] };
        result.push(group);
      }
      group.items.push(tx);
    });
    return result;
  }, [transactions, filter, locale]);

  async function afterChange() {
    if (selectedId) await Promise.all([loadTransactions(selectedId), refreshAccounts()]);
  }

  async function deleteAccount(account: FinanceAccount) {
    if (!(await confirm({ message: t("deleteAccountConfirm", { name: account.name }), tone: "danger", confirmLabel: tMobile("common.delete") }))) return;
    try {
      await browserApiFetch(`/api/finance/accounts/${account.id}`, { method: "DELETE" });
      const list = await refreshAccounts();
      setSelectedId(list[0]?.id ?? null);
      setAccountSheet(null);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteAccountFailed"), "error");
    }
  }

  return (
    <div className="mobile-page mobile-page-list">
      <MobileSubHeader
        title={t("pageTitle")}
        subtitle={t("pageDescription")}
        backLabel={tMobile("tabs.more")}
        onBack={openMore}
        actions={
          canWrite ? (
            <button type="button" className="mobile-icon-button" aria-label={t("createAccount")} onClick={() => setAccountSheet("new")}>
              <MobileIcon name="plus" />
            </button>
          ) : undefined
        }
      />
      {accounts.length === 0 ? (
        <MobileEmpty title={t("emptyTitle")} hint={canWrite ? t("addTransactionFirstHint") : t("emptyDescription")} />
      ) : (
        <>
          <div className="mobile-section">
            <div className="mobile-hscroll">
              {accounts.map((account) => (
                <button
                  key={account.id}
                  type="button"
                  className={`mobile-account-card${account.id === selectedId ? " mobile-account-card-active" : ""}`}
                  onClick={() => (account.id === selectedId && canWrite ? setAccountSheet(account) : setSelectedId(account.id))}
                >
                  <span className="mobile-eyebrow">{account.name}</span>
                  <span className={`mobile-stat-value${account.balance < 0 ? " mobile-amount-neg" : ""}`}>{money(account.balance, account.currency_label)}</span>
                  <span className="mobile-muted-sm">
                    {Math.sign(account.provisional_balance) === 1
                      ? `+ ${money(account.provisional_balance, account.currency_label)} ${t("provisional")}`
                      : t("transactionCount", { count: account.transaction_count })}
                  </span>
                </button>
              ))}
            </div>
          </div>
          <MobileChipRow>
            {(["all", "income", "expense", "year"] as TxFilter[]).map((value) => (
              <MobileChip key={value} active={filter === value} onClick={() => setFilter(value)}>
                {value === "all" ? t("filterAll") : value === "income" ? t("income") : value === "expense" ? t("expense") : tMobile("finances.thisYear")}
              </MobileChip>
            ))}
          </MobileChipRow>
          {groups.map((group) => (
            <section key={group.key} className="mobile-list-group">
              <div className="mobile-list-group-header">
                <span className="mobile-list-group-title">{group.label}</span>
              </div>
              <div className="mobile-card mobile-list-card">
                {group.items.map((tx) => (
                  <MobileListRow
                    key={tx.id}
                    onClick={canWrite ? () => setTxSheet(tx) : undefined}
                    chevron={false}
                    label={
                      <span className="mobile-row-stack">
                        <span className="mobile-row-title">{tx.description}</span>
                        <span className="mobile-row-meta">{dateParts.dayMonth(tx.transaction_date, locale)}</span>
                      </span>
                    }
                    trailing={
                      <span className={`mobile-amount ${tx.amount < 0 ? "mobile-amount-neg" : "mobile-amount-pos"}`}>
                        {tx.amount > 0 ? "+ " : "− "}
                        {money(Math.abs(tx.amount))}
                      </span>
                    }
                  />
                ))}
              </div>
            </section>
          ))}
          {groups.length === 0 ? <MobileEmpty title={t("noTransactions")} /> : null}
        </>
      )}

      {canWrite && selected ? <MobileFab label={tMobile("finances.fab")} onClick={() => setTxSheet("new")} /> : null}

      {txSheet && selected ? (
        <TransactionSheet
          account={selected}
          transaction={txSheet === "new" ? null : txSheet}
          onClose={() => setTxSheet(null)}
          onSaved={async () => {
            setTxSheet(null);
            await afterChange();
          }}
        />
      ) : null}
      {accountSheet ? (
        <AccountSheet
          account={accountSheet === "new" ? null : accountSheet}
          onClose={() => setAccountSheet(null)}
          onDelete={(account) => void deleteAccount(account)}
          onSaved={async (account) => {
            setAccountSheet(null);
            await refreshAccounts();
            setSelectedId(account.id);
          }}
        />
      ) : null}
    </div>
  );
}

function TransactionSheet({
  account,
  transaction,
  onClose,
  onSaved,
}: {
  account: FinanceAccount;
  transaction: FinanceTransaction | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const t = useTranslations("finances");
  const tMobile = useTranslations("mobile");
  const confirm = useConfirm();
  const showToast = useToast();
  const [direction, setDirection] = useState<"income" | "expense">(Math.sign(transaction?.amount ?? 0) === -1 ? "expense" : "income");
  const [amount, setAmount] = useState(transaction ? String(Math.abs(transaction.amount)) : "");
  const [description, setDescription] = useState(transaction?.description ?? "");
  const [date, setDate] = useState(transaction?.transaction_date ?? todayIso());
  const [saving, setSaving] = useState(false);
  const parsed = Number(amount.replace(",", "."));
  const valid = description.trim().length > 0 && !!date && Number.isFinite(parsed) && parsed > 0;

  async function save() {
    if (!valid || saving) return;
    setSaving(true);
    const body = JSON.stringify({ amount: direction === "expense" ? -parsed : parsed, description: description.trim(), transaction_date: date });
    try {
      if (transaction) await browserApiFetch(`/api/finance/transactions/${transaction.id}`, { method: "PATCH", body });
      else await browserApiFetch(`/api/finance/accounts/${account.id}/transactions`, { method: "POST", body });
      await onSaved();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("saveTxFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!transaction || !(await confirm({ message: t("deleteTxConfirm"), tone: "danger", confirmLabel: tMobile("common.delete") }))) return;
    try {
      await browserApiFetch(`/api/finance/transactions/${transaction.id}`, { method: "DELETE" });
      await onSaved();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteTxFailed"), "error");
    }
  }

  return (
    <Modal
      open
      size="sheet"
      title={transaction ? t("editTransactionTitle") : t("newTransactionTitle")}
      description={account.name}
      onClose={onClose}
      className="mobile-sheet"
      footer={
        <div className="modal-actions mobile-sheet-footer">
          {transaction ? (
            <button type="button" className="button-danger" onClick={() => void remove()}>
              {tMobile("common.delete")}
            </button>
          ) : (
            <button type="button" className="button-ghost" onClick={onClose}>
              {tMobile("common.cancel")}
            </button>
          )}
          <button type="button" className="button-primary" data-modal-save disabled={!valid || saving} onClick={() => void save()}>
            {transaction ? t("update") : tMobile("finances.add")}
          </button>
        </div>
      }
    >
      <div className="grid mobile-sheet-body">
        <MobileSegmented<"income" | "expense">
          ariaLabel={t("amountLabel")}
          value={direction}
          onChange={setDirection}
          options={[
            { value: "income", label: t("income") },
            { value: "expense", label: t("expense") },
          ]}
        />
        <label className="field-stack">
          <span className="field-label">{t("amountWithCurrencyLabel", { currency: account.currency_label })}</span>
          <input className="mobile-amount-input" inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="0.00" />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("txDescriptionLabel")}</span>
          <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder={t("txDescriptionPlaceholder")} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("dateLabel")}</span>
          <DateInput value={date} onChange={setDate} />
        </label>
      </div>
    </Modal>
  );
}

function AccountSheet({
  account,
  onClose,
  onSaved,
  onDelete,
}: {
  account: FinanceAccount | null;
  onClose: () => void;
  onSaved: (account: FinanceAccount) => Promise<void>;
  onDelete: (account: FinanceAccount) => void;
}) {
  const t = useTranslations("finances");
  const tMobile = useTranslations("mobile");
  const showToast = useToast();
  const [name, setName] = useState(account?.name ?? "");
  const [currency, setCurrency] = useState(account?.currency_label ?? "CHF");
  const [description, setDescription] = useState(account?.description ?? "");
  const [saving, setSaving] = useState(false);
  const valid = name.trim().length > 0 && currency.trim().length > 0;

  async function save() {
    if (!valid || saving) return;
    setSaving(true);
    const body = JSON.stringify({ name: name.trim(), currency_label: currency.trim(), description: description.trim() || null });
    try {
      const saved = account
        ? await browserApiFetch<FinanceAccount>(`/api/finance/accounts/${account.id}`, { method: "PATCH", body })
        : await browserApiFetch<FinanceAccount>("/api/finance/accounts", { method: "POST", body });
      await onSaved(saved);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("saveAccountFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open
      size="sheet"
      title={account ? t("editAccountTitle") : t("newAccountTitle")}
      description={t("accountModalDescription")}
      onClose={onClose}
      className="mobile-sheet"
      footer={
        <div className="modal-actions mobile-sheet-footer">
          {account ? (
            <button type="button" className="button-danger" onClick={() => onDelete(account)}>
              {tMobile("common.delete")}
            </button>
          ) : (
            <button type="button" className="button-ghost" onClick={onClose}>
              {tMobile("common.cancel")}
            </button>
          )}
          <button type="button" className="button-primary" data-modal-save disabled={!valid || saving} onClick={() => void save()}>
            {tMobile("common.save")}
          </button>
        </div>
      }
    >
      <div className="grid mobile-sheet-body">
        <label className="field-stack">
          <span className="field-label">{t("nameLabel")}</span>
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder={t("namePlaceholder")} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("currencyLabel")}</span>
          <input value={currency} onChange={(event) => setCurrency(event.target.value)} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("descriptionLabel")}</span>
          <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder={t("descriptionPlaceholder")} />
        </label>
        <p className="mobile-desktop-hint-text">{t("emptyHint")}</p>
      </div>
    </Modal>
  );
}

// ── Bussen ──────────────────────────────────────────────────────────────

type FineFilter = "pending" | "collected" | "all";

export function MobileFines({
  initialFines,
  accounts,
  canWrite,
  ownOnly,
}: {
  initialFines: AttendanceFineListItem[];
  accounts: FinanceAccount[];
  canWrite: boolean;
  ownOnly: boolean;
}) {
  const t = useTranslations("finances");
  const tMobile = useTranslations("mobile");
  const fineTypeLabel = useMemo(() => fineTypeLabels(t), [t]);
  const locale = useLocale();
  const openMore = useOpenMore();
  const confirm = useConfirm();
  const showToast = useToast();
  const [fines, setFines] = useAllPages<AttendanceFineListItem>("/api/fines", initialFines);
  const [filter, setFilter] = useState<FineFilter>("pending");
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const accountName = (id: string) => accounts.find((account) => account.id === id)?.name ?? t("unknownAccount");

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return fines
      .filter((fine) => (filter === "all" ? true : fine.status === filter))
      .filter((fine) => !needle || `${fine.participant_name_snapshot} ${fine.protocol_number ?? ""}`.toLowerCase().includes(needle))
      .sort((a, b) => (b.protocol_date ?? "").localeCompare(a.protocol_date ?? ""));
  }, [fines, filter, search]);
  const pending = fines.filter((fine) => fine.status === "pending");
  const pendingTotal = pending.reduce((sum, fine) => sum + fine.amount, 0);
  const pendingPeople = new Set(pending.map((fine) => fine.participant_id ?? fine.participant_name_snapshot)).size;
  const openFine = fines.find((fine) => fine.id === openId) ?? null;

  function replace(updated: AttendanceFineListItem) {
    setFines((list) => list.map((fine) => (fine.id === updated.id ? { ...fine, ...updated } : fine)));
  }

  async function collect(fine: AttendanceFineListItem) {
    try {
      const updated = await browserApiFetch<AttendanceFineListItem>(`/api/fines/${fine.id}/collect`, { method: "POST" });
      replace(updated);
      setOpenId(null);
      showToast(tMobile("fines.collected", { name: fine.participant_name_snapshot }), "success", {
        action: { label: t("reopen"), onClick: () => void reopen(fine) },
      });
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("collectFailed"), "error");
    }
  }

  async function reopen(fine: AttendanceFineListItem) {
    try {
      replace(await browserApiFetch<AttendanceFineListItem>(`/api/fines/${fine.id}/reopen`, { method: "POST" }));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("reopenFailed"), "error");
    }
  }

  async function remove(fine: AttendanceFineListItem) {
    if (!(await confirm({ message: t("deleteFineConfirm", { name: fine.participant_name_snapshot }), tone: "danger", confirmLabel: tMobile("common.delete") }))) return;
    try {
      await browserApiFetch(`/api/fines/${fine.id}`, { method: "DELETE" });
      setFines((list) => list.filter((item) => item.id !== fine.id));
      setOpenId(null);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteFineFailed"), "error");
    }
  }

  async function reload() {
    setFines((await browserApiFetch<AttendanceFineListItem[]>("/api/fines?limit=500")) ?? []);
  }

  return (
    <div className="mobile-page mobile-page-list">
      <MobileSubHeader title={t("finesPageTitle")} subtitle={ownOnly ? t("ownOnlyDescription") : t("allDescription")} backLabel={tMobile("tabs.more")} onBack={openMore} />
      <div className="mobile-section">
        <MobileSegmented<FineFilter>
          ariaLabel={t("colStatus")}
          value={filter}
          onChange={setFilter}
          options={[
            { value: "pending", label: t("filterPending") },
            { value: "collected", label: t("filterCollected") },
            { value: "all", label: t("filterAll") },
          ]}
        />
        <MobileStat
          label={t("filterPending")}
          value={money(pendingTotal, pending[0]?.currency_label ?? "CHF")}
          sub={tMobile("dashboard.finePeople", { count: pendingPeople })}
        />
        <SearchInput value={search} onChange={setSearch} placeholder={t("finesSearchPlaceholder")} />
      </div>
      {visible.length > 0 ? (
        <div className="mobile-section">
          <div className="mobile-card mobile-list-card">
            {visible.map((fine) => (
              <MobileListRow
                key={fine.id}
                onClick={() => setOpenId(fine.id)}
                leading={<MobileAvatar name={fine.participant_name_snapshot} size="sm" />}
                label={
                  <span className="mobile-row-stack">
                    <span className="mobile-row-title">{fine.participant_name_snapshot}</span>
                    <span className="mobile-row-meta">
                      {[fineTypeLabel[fine.fine_type] ?? fine.fine_type, fine.protocol_number].filter(Boolean).join(" · ")}
                    </span>
                    {filter === "all" ? (
                      <span className="mobile-row-pills">
                        <span className={fine.status === "collected" ? "mobile-cycle-pill" : "mobile-overdue-pill"}>
                          {fine.status === "collected" ? t("statusCollected") : t("statusPending")}
                        </span>
                      </span>
                    ) : null}
                  </span>
                }
                trailing={<span className="mobile-amount">{money(fine.amount)}</span>}
              />
            ))}
          </div>
        </div>
      ) : (
        <MobileEmpty title={fines.length ? t("emptyFines") : t("noFinesTitle")} hint={fines.length ? undefined : t("noFinesHint")} />
      )}

      {canWrite ? <MobileFab label={tMobile("fines.fab")} onClick={() => setCreating(true)} /> : null}

      {openFine ? (
        <Modal
          open
          size="sheet"
          title={openFine.participant_name_snapshot}
          description={[openFine.protocol_number, openFine.protocol_date ? dateParts.dayMonth(openFine.protocol_date, locale) : null].filter(Boolean).join(" · ")}
          onClose={() => setOpenId(null)}
          className="mobile-sheet"
          footer={
            canWrite ? (
              <div className="modal-actions mobile-sheet-footer">
                <button type="button" className="button-danger" onClick={() => void remove(openFine)}>
                  {tMobile("common.delete")}
                </button>
                {openFine.status === "pending" ? (
                  <button type="button" className="button-primary" onClick={() => void collect(openFine)}>
                    {t("markCollected")}
                  </button>
                ) : openFine.can_reopen ? (
                  <button type="button" className="button-secondary" onClick={() => void reopen(openFine)}>
                    {t("reopen")}
                  </button>
                ) : null}
              </div>
            ) : undefined
          }
        >
          <div className="mobile-card mobile-group-card">
            <MobileListRow label={t("colReason")} value={fineTypeLabel[openFine.fine_type] ?? openFine.fine_type} />
            <MobileListRow label={t("colProtocol")} value={openFine.protocol_number ?? "—"} />
            <MobileListRow label={t("colAccount")} value={accountName(openFine.account_id)} />
            <MobileListRow label={t("amountLabel")} value={<strong>{money(openFine.amount, openFine.currency_label)}</strong>} />
            <MobileListRow
              label={t("colStatus")}
              value={
                openFine.status === "collected"
                  ? `${t("statusCollected")}${openFine.collected_at ? ` · ${dateParts.dayMonth(openFine.collected_at.slice(0, 10), locale)}` : ""}`
                  : t("statusPending")
              }
            />
          </div>
        </Modal>
      ) : null}
      <FineCreateModal open={creating} accounts={accounts} onClose={() => setCreating(false)} onCreated={() => void reload()} />
    </div>
  );
}
