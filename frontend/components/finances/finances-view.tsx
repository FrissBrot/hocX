"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { DateInput } from "@/components/ui/date-input";
import { EmptyState } from "@/components/ui/empty-state";
import { ActionIcon } from "@/components/ui/action-icons";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { FinanceAccount, FinanceTransaction } from "@/types/api";
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { formatDate } from "@/lib/utils/format";

const PAGE_SIZE = 50;

type Props = { initialAccounts: FinanceAccount[]; canWrite: boolean };

export function FinancesView({ initialAccounts, canWrite }: Props) {
  const t = useTranslations("finances");
  const tCommon = useTranslations("common");
  const locale = useLocale();
  const confirm = useConfirm();
  const showToast = useToast();
  const [accounts, setAccounts] = useState(initialAccounts);
  const [selected, setSelected] = useState<FinanceAccount | null>(null);
  const [transactions, setTransactions] = useState<FinanceTransaction[]>([]);
  const [loadingTx, setLoadingTx] = useState(false);
  const [hasMoreTx, setHasMoreTx] = useState(false);
  const [isLoadingMoreTx, setIsLoadingMoreTx] = useState(false);

  // Account form
  const [showAccountForm, setShowAccountForm] = useState(false);
  const [editingAccount, setEditingAccount] = useState<FinanceAccount | null>(null);
  const [accountDraft, setAccountDraft] = useState({ name: "", currency_label: "CHF", description: "" });
  const [savingAccount, setSavingAccount] = useState(false);

  // Transaction form
  const [showTxForm, setShowTxForm] = useState(false);
  const [editingTx, setEditingTx] = useState<FinanceTransaction | null>(null);
  const [txDraft, setTxDraft] = useState({ amount: "", description: "", transaction_date: today() });
  const [savingTx, setSavingTx] = useState(false);
  const [txDirection, setTxDirection] = useState<"income" | "expense">("income");
  const parsedTxAmount = Number(txDraft.amount.replace(",", "."));
  const validTx = Boolean(txDraft.description.trim() && txDraft.transaction_date && Number.isFinite(parsedTxAmount) && parsedTxAmount > 0);

  async function openAccount(account: FinanceAccount) {
    setSelected(account);
    setShowTxForm(false);
    setEditingTx(null);
    await reloadFirstPage(account.id);
  }

  async function reloadFirstPage(accountId: string) {
    setLoadingTx(true);
    try {
      const data = await browserApiFetch<FinanceTransaction[]>(
        `/api/finance/accounts/${accountId}/transactions?limit=${PAGE_SIZE}`
      );
      setTransactions(data ?? []);
      setHasMoreTx((data ?? []).length === PAGE_SIZE);
    } finally {
      setLoadingTx(false);
    }
  }

  async function loadMoreTx() {
    if (!selected) return;
    setIsLoadingMoreTx(true);
    try {
      const next = await browserApiFetch<FinanceTransaction[]>(
        `/api/finance/accounts/${selected.id}/transactions?skip=${transactions.length}&limit=${PAGE_SIZE}`
      );
      setTransactions((current) => [...current, ...next]);
      setHasMoreTx(next.length === PAGE_SIZE);
    } finally {
      setIsLoadingMoreTx(false);
    }
  }

  const loadMoreTxSentinelRef = useInfiniteScroll({
    hasMore: hasMoreTx,
    isLoading: isLoadingMoreTx,
    onLoadMore: () => void loadMoreTx(),
  });

  // The account's balance/transaction_count are only authoritative from the backend's
  // aggregate query (list_accounts) — refetch it instead of resumming the currently
  // loaded transaction page, which since pagination only ever holds a partial view.
  async function refreshAccounts(accountId: string) {
    const data = await browserApiFetch<FinanceAccount[]>("/api/finance/accounts");
    if (!data) return;
    setAccounts(data);
    const updated = data.find((a) => a.id === accountId);
    if (updated) setSelected(updated);
  }

  // ── Account CRUD ────────────────────────────────────────────────────────────

  function startCreateAccount() {
    setEditingAccount(null);
    setAccountDraft({ name: "", currency_label: "CHF", description: "" });
    setShowAccountForm(true);
  }

  function startEditAccount(account: FinanceAccount, e: React.MouseEvent) {
    e.stopPropagation();
    setEditingAccount(account);
    setAccountDraft({ name: account.name, currency_label: account.currency_label, description: account.description ?? "" });
    setShowAccountForm(true);
  }

  async function saveAccount() {
    if (savingAccount || !accountDraft.name.trim()) return;
    setSavingAccount(true);
    try {
      if (editingAccount) {
        const updated = await browserApiFetch<FinanceAccount>(`/api/finance/accounts/${editingAccount.id}`, {
          method: "PATCH",
          body: JSON.stringify({ name: accountDraft.name, currency_label: accountDraft.currency_label, description: accountDraft.description || null }),
        });
        if (updated) {
          setAccounts((prev) => prev.map((a) => a.id === updated.id ? { ...a, name: updated.name, currency_label: updated.currency_label, description: updated.description } : a));
          if (selected?.id === updated.id) setSelected((prev) => prev ? { ...prev, ...updated } : prev);
        }
      } else {
        const created = await browserApiFetch<FinanceAccount>("/api/finance/accounts", {
          method: "POST",
          body: JSON.stringify({ name: accountDraft.name, currency_label: accountDraft.currency_label, description: accountDraft.description || null }),
        });
        if (created) setAccounts((prev) => [...prev, created]);
      }
      setShowAccountForm(false);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("saveAccountFailed"), "error");
    } finally {
      setSavingAccount(false);
    }
  }

  async function deleteAccount(account: FinanceAccount, e: React.MouseEvent) {
    e.stopPropagation();
    if (!(await confirm({ message: t("deleteAccountConfirm", { name: account.name }), tone: "danger", confirmLabel: tCommon("delete") }))) return;
    try {
      await browserApiFetch(`/api/finance/accounts/${account.id}`, { method: "DELETE" });
      setAccounts((prev) => prev.filter((a) => a.id !== account.id));
      if (selected?.id === account.id) { setSelected(null); setTransactions([]); }
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteAccountFailed"), "error");
    }
  }

  // ── Transaction CRUD ─────────────────────────────────────────────────────────

  function startCreateTx() {
    setTxDirection("income");
    setEditingTx(null);
    setTxDraft({ amount: "", description: "", transaction_date: today() });
    setShowTxForm(true);
  }

  function startEditTx(tx: FinanceTransaction) {
    setEditingTx(tx);
    setTxDirection(tx.amount < 0 ? "expense" : "income");
    setTxDraft({ amount: String(Math.abs(tx.amount)), description: tx.description, transaction_date: tx.transaction_date });
    setShowTxForm(true);
  }

  async function saveTx() {
    if (!selected || savingTx || !validTx) return;
    const amount = txDirection === "expense" ? -parsedTxAmount : parsedTxAmount;
    setSavingTx(true);
    try {
      if (editingTx) {
        await browserApiFetch<FinanceTransaction>(`/api/finance/transactions/${editingTx.id}`, {
          method: "PATCH",
          body: JSON.stringify({ amount, description: txDraft.description, transaction_date: txDraft.transaction_date }),
        });
      } else {
        await browserApiFetch<FinanceTransaction>(`/api/finance/accounts/${selected.id}/transactions`, {
          method: "POST",
          body: JSON.stringify({ amount, description: txDraft.description, transaction_date: txDraft.transaction_date }),
        });
      }
      // A single mutated transaction can shift the running balance of every transaction
      // after it, so reload the first page fresh rather than patching state locally.
      await Promise.all([reloadFirstPage(selected.id), refreshAccounts(selected.id)]);
      setShowTxForm(false);
      setEditingTx(null);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("saveTxFailed"), "error");
    } finally {
      setSavingTx(false);
    }
  }

  async function deleteTx(tx: FinanceTransaction) {
    if (!selected) return;
    if (!(await confirm({ message: t("deleteTxConfirm"), tone: "danger", confirmLabel: tCommon("delete") }))) return;
    try {
      await browserApiFetch(`/api/finance/transactions/${tx.id}`, { method: "DELETE" });
      await Promise.all([reloadFirstPage(selected.id), refreshAccounts(selected.id)]);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteTxFailed"), "error");
    }
  }

  const currency = selected?.currency_label ?? "";

  const accountModal = (
    <>
    {canWrite && (
      <Modal
        open={showAccountForm}
        title={editingAccount ? t("editAccountTitle") : t("newAccountTitle")}
        description={t("accountModalDescription")}
        className="finance-account-modal"
        onClose={() => setShowAccountForm(false)}
      >
        <ModalSaveForm className="grid finance-form-modal" onSubmit={(event) => { event.preventDefault(); return saveAccount(); }}>
          <label className="field-stack">
            <span className="field-label">{t("nameLabel")}</span>
            <input value={accountDraft.name} onChange={(e) => setAccountDraft((d) => ({ ...d, name: e.target.value }))} placeholder={t("namePlaceholder")} required autoFocus />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("currencyLabel")}</span>
            <input value={accountDraft.currency_label} onChange={(e) => setAccountDraft((d) => ({ ...d, currency_label: e.target.value }))} placeholder="CHF" />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("descriptionLabel")}</span>
            <textarea rows={3} value={accountDraft.description} onChange={(e) => setAccountDraft((d) => ({ ...d, description: e.target.value }))} placeholder={t("descriptionPlaceholder")} />
          </label>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setShowAccountForm(false)}>{tCommon("cancel")}</button>
            <button data-modal-save type="submit" className="button-primary" disabled={savingAccount || !accountDraft.name.trim()}>
              {savingAccount ? t("saving") : tCommon("save")}
            </button>
          </div>
        </ModalSaveForm>
      </Modal>
    )}
    </>
  );


  if (accounts.length === 0) {
    return (
      <div className="grid">
        <div className="page-header">
          <div>
            <h1 className="page-title">{t("pageTitle")}</h1>
            <p className="muted">{t("pageDescription")}</p>
          </div>
        </div>
        <EmptyState
          title={t("emptyTitle")}
          description={t("emptyDescription")}
          actions={
            canWrite ? (
              <>
                <button
                  type="button"
                  className="button-primary"
                  onClick={() => {
                    showToast(t("addTransactionFirstHint"), "info");
                    startCreateAccount();
                  }}
                >
                  {t("addTransaction")}
                </button>
                <button type="button" className="button-secondary" onClick={startCreateAccount}>
                  {t("createAccount")}
                </button>
              </>
            ) : null
          }
          hint={t("emptyHint")}
        />
        {accountModal}
      </div>
    );
  }

  return (
    <div className="finance-layout">
      {/* ── Account sidebar ── */}
      <aside className="finance-sidebar">
        <div className="finance-sidebar-header">
          <span className="finance-sidebar-title">{t("accountsLabel")}</span>
          {canWrite && <button type="button" className="button-icon-soft" onClick={startCreateAccount} title={t("createAccountAria")} aria-label={t("createAccountAria")}><ActionIcon name="add" /></button>}
        </div>

        <div className="finance-account-list">
          {accounts.map((account) => (
            <div
              key={account.id}
              role="button"
              tabIndex={0}
              className={`finance-account-card${selected?.id === account.id ? " finance-account-card-active" : ""}`}
              onClick={() => void openAccount(account)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") void openAccount(account); }}
            >
              <div className="finance-account-name">{account.name}</div>
              <div className={`finance-account-balance${account.balance < 0 ? " finance-balance-negative" : ""}`}>
                {formatAmount(account.balance, account.currency_label, locale)}
              </div>
              {account.provisional_balance > 0 ? (
                <div className="finance-account-provisional">
                  + {formatAmount(account.provisional_balance, account.currency_label, locale)} {t("provisional")}
                </div>
              ) : null}
              {account.description ? <div className="finance-account-desc">{account.description}</div> : null}
              <div className="finance-account-actions">
                <span className="finance-account-count">{t("transactionCount", { count: account.transaction_count })}</span>
                {canWrite && <button type="button" className="button-icon-soft-sm" onClick={(e) => startEditAccount(account, e)} title={tCommon("edit")} aria-label={tCommon("edit")}><ActionIcon name="edit" /></button>}
                {canWrite && <button type="button" className="button-icon-soft-sm button-icon-soft-danger" onClick={(e) => void deleteAccount(account, e)} title={tCommon("delete")} aria-label={tCommon("delete")}><ActionIcon name="delete" /></button>}
              </div>
            </div>
          ))}
        </div>

        {accountModal}
      </aside>

      {/* ── Transaction panel ── */}
      <main className="finance-main">
        {!selected ? (
          <div className="finance-placeholder">
            <p className="muted">{t("selectAccountHint")}</p>
          </div>
        ) : (
          <>
            <div className="finance-main-header">
              <div>
                <h2 className="finance-main-title">{selected.name}</h2>
                <div className={`finance-main-balance${selected.balance < 0 ? " finance-balance-negative" : ""}`}>
                  {formatAmount(selected.balance, selected.currency_label, locale, true)}
                </div>
                {selected.provisional_balance > 0 ? (
                  <div className="finance-account-provisional">
                    + {formatAmount(selected.provisional_balance, selected.currency_label, locale, true)} {t("provisionalPending")}
                  </div>
                ) : null}
              </div>
              {canWrite && !showTxForm && <button type="button" className="button-secondary" onClick={startCreateTx}>{t("addTransaction")}</button>}
            </div>

            {canWrite && showTxForm && (
              <form className="grid finance-tx-form" onSubmit={(event) => { event.preventDefault(); void saveTx(); }} onKeyDown={(event) => { if (event.key === "Escape" && !savingTx) { setShowTxForm(false); setEditingTx(null); } }}>
                <div className="finance-tx-form-header">
                  <h3 className="finance-tx-form-title">{editingTx ? t("editTransactionTitle") : t("newTransactionTitle")}</h3>
                  <div className={`finance-tx-direction finance-tx-direction-${txDirection}`}>
                    <FilterTabs options={[{ value: "income", label: t("income") }, { value: "expense", label: t("expense") }]} value={txDirection} onChange={setTxDirection} />
                  </div>
                  <button type="button" className="button-icon-soft finance-tx-close" aria-label={tCommon("close")} disabled={savingTx} onClick={() => { setShowTxForm(false); setEditingTx(null); }}><ActionIcon name="close" /></button>
                </div>
                <div className="finance-tx-form-row">
                  <label className="field-stack finance-tx-field-amount">
                    <span className="field-label">{t("amountLabel")}</span>
                    <span className="finance-tx-amount-input">
                      <span className="finance-tx-currency" aria-hidden="true">{currency}</span>
                      <input
                        value={txDraft.amount}
                        onChange={(e) => setTxDraft((d) => ({ ...d, amount: e.target.value }))}
                        aria-label={t("amountWithCurrencyLabel", { currency })}
                        inputMode="decimal"
                        placeholder="0.00"
                        required
                        autoFocus
                      />
                    </span>
                  </label>
                  <label className="field-stack finance-tx-field-desc">
                    <span className="field-label">{t("txDescriptionLabel")}</span>
                    <input
                      value={txDraft.description}
                      onChange={(e) => setTxDraft((d) => ({ ...d, description: e.target.value }))}
                      placeholder={t("txDescriptionPlaceholder")}
                      required
                    />
                  </label>
                  <div className="field-stack finance-tx-field-date">
                    <label className="field-label" htmlFor="finance-tx-date">{t("dateLabel")}</label>
                    <div className="finance-tx-date-input">
                      <DateInput id="finance-tx-date" value={txDraft.transaction_date} onChange={(value) => setTxDraft((d) => ({ ...d, transaction_date: value }))} required />
                      <button type="button" className="button-ghost finance-tx-today" onClick={() => setTxDraft((d) => ({ ...d, transaction_date: today() }))}>{t("today")}</button>
                    </div>
                  </div>
                </div>
                <div className="finance-tx-form-footer">
                  <p className="finance-tx-booking-note">{t.rich("bookedTo", { account: selected.name, strong: (chunks) => <strong>{chunks}</strong> })}</p>
                  <div className="finance-form-actions">
                    <button type="button" className="button-secondary" disabled={savingTx} onClick={() => { setShowTxForm(false); setEditingTx(null); }}>{tCommon("cancel")}</button>
                    <button type="submit" className="button-primary" disabled={savingTx || !validTx}>
                      {savingTx ? t("saving") : editingTx ? t("update") : tCommon("add")}
                    </button>
                  </div>
                </div>
              </form>
            )}

            {loadingTx ? (
              <p className="muted">{tCommon("loading")}</p>
            ) : transactions.length === 0 ? (
              <p className="muted finance-empty">{t("noTransactions")}</p>
            ) : (
              <div className="finance-tx-table">
                <div className="finance-tx-header">
                  <span>{t("colDate")}</span>
                  <span>{t("colDescription")}</span>
                  <span className="finance-tx-cell-right">{t("colAmount")}</span>
                  <span className="finance-tx-cell-right">{t("colBalance")}</span>
                  <span></span>
                </div>
                {transactions.map((tx) => {
                  const running = tx.running_balance ?? tx.amount;
                  return (
                    <div key={tx.id} className={`finance-tx-row${tx.amount < 0 ? " finance-tx-expense" : " finance-tx-income"}`}>
                      <span className="finance-tx-date">{formatDate(tx.transaction_date)}</span>
                      <span className="finance-tx-desc">
                        {tx.description}
                      </span>
                      <span className={`finance-tx-amount finance-tx-cell-right${tx.amount < 0 ? " finance-amount-neg" : " finance-amount-pos"}`}>
                        {tx.amount > 0 ? "+" : ""}{formatAmount(tx.amount, currency, locale)}
                      </span>
                      <span className={`finance-tx-running finance-tx-cell-right${running < 0 ? " finance-balance-negative" : ""}`}>
                        {formatAmount(running, currency, locale)}
                      </span>
                      <span className="finance-tx-actions">
                        {canWrite && <button type="button" className="button-icon-soft-sm" onClick={() => startEditTx(tx)} title={tCommon("edit")} aria-label={tCommon("edit")}><ActionIcon name="edit" /></button>}
                        {canWrite && <button type="button" className="button-icon-soft-sm button-icon-soft-danger" onClick={() => void deleteTx(tx)} title={tCommon("delete")} aria-label={tCommon("delete")}><ActionIcon name="delete" /></button>}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            {hasMoreTx && (
              <div className="load-more-row" ref={loadMoreTxSentinelRef}>
                {isLoadingMoreTx ? (
                  <span className="muted">{t("loadingMore")}</span>
                ) : (
                  <button type="button" className="button-secondary button-ghost" onClick={() => void loadMoreTx()}>
                    {t("loadMore", { count: transactions.length })}
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function today(): string {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function formatAmount(amount: number, currency: string, locale: string, currencyFirst = false): string {
  const abs = Math.abs(amount).toFixed(2);
  const formatted = Number(abs).toLocaleString(`${locale}-CH`, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const value = `${amount < 0 ? "−" : ""}${formatted}`;
  return currencyFirst ? `${currency} ${value}` : `${value} ${currency}`;
}
