"use client";

import { useState } from "react";
import { DateInput } from "@/components/ui/date-input";
import { FinanceAccount, FinanceTransaction } from "@/types/api";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate } from "@/lib/utils/format";

type Props = { initialAccounts: FinanceAccount[] };

export function FinancesView({ initialAccounts }: Props) {
  const [accounts, setAccounts] = useState(initialAccounts);
  const [selected, setSelected] = useState<FinanceAccount | null>(null);
  const [transactions, setTransactions] = useState<FinanceTransaction[]>([]);
  const [loadingTx, setLoadingTx] = useState(false);

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

  async function openAccount(account: FinanceAccount) {
    setSelected(account);
    setLoadingTx(true);
    setTransactions([]);
    setShowTxForm(false);
    setEditingTx(null);
    try {
      const data = await browserApiFetch<FinanceTransaction[]>(`/api/finance/accounts/${account.id}/transactions`);
      setTransactions(data ?? []);
    } finally {
      setLoadingTx(false);
    }
  }

  function refreshAccountBalance(accountId: number, txList: FinanceTransaction[]) {
    const balance = txList.reduce((sum, t) => sum + t.amount, 0);
    setAccounts((prev) =>
      prev.map((a) =>
        a.id === accountId
          ? { ...a, balance, transaction_count: txList.length }
          : a
      )
    );
    if (selected?.id === accountId) {
      setSelected((prev) => prev ? { ...prev, balance, transaction_count: txList.length } : prev);
    }
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
    if (!accountDraft.name.trim()) return;
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
    } finally {
      setSavingAccount(false);
    }
  }

  async function deleteAccount(account: FinanceAccount, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm(`Konto "${account.name}" und alle Transaktionen löschen?`)) return;
    await browserApiFetch(`/api/finance/accounts/${account.id}`, { method: "DELETE" });
    setAccounts((prev) => prev.filter((a) => a.id !== account.id));
    if (selected?.id === account.id) { setSelected(null); setTransactions([]); }
  }

  // ── Transaction CRUD ─────────────────────────────────────────────────────────

  function startCreateTx() {
    setEditingTx(null);
    setTxDraft({ amount: "", description: "", transaction_date: today() });
    setShowTxForm(true);
  }

  function startEditTx(tx: FinanceTransaction) {
    setEditingTx(tx);
    setTxDraft({ amount: String(tx.amount), description: tx.description, transaction_date: tx.transaction_date });
    setShowTxForm(true);
  }

  async function saveTx() {
    if (!selected || !txDraft.description.trim() || !txDraft.amount) return;
    const amount = parseFloat(txDraft.amount.replace(",", "."));
    if (isNaN(amount)) return;
    setSavingTx(true);
    try {
      let updated: FinanceTransaction[] = transactions;
      if (editingTx) {
        const result = await browserApiFetch<FinanceTransaction>(`/api/finance/transactions/${editingTx.id}`, {
          method: "PATCH",
          body: JSON.stringify({ amount, description: txDraft.description, transaction_date: txDraft.transaction_date }),
        });
        if (result) updated = transactions.map((t) => t.id === result.id ? result : t);
      } else {
        const result = await browserApiFetch<FinanceTransaction>(`/api/finance/accounts/${selected.id}/transactions`, {
          method: "POST",
          body: JSON.stringify({ amount, description: txDraft.description, transaction_date: txDraft.transaction_date }),
        });
        if (result) updated = [result, ...transactions];
      }
      setTransactions(updated);
      refreshAccountBalance(selected.id, updated);
      setShowTxForm(false);
      setEditingTx(null);
    } finally {
      setSavingTx(false);
    }
  }

  async function deleteTx(tx: FinanceTransaction) {
    if (!selected) return;
    await browserApiFetch(`/api/finance/transactions/${tx.id}`, { method: "DELETE" });
    const updated = transactions.filter((t) => t.id !== tx.id);
    setTransactions(updated);
    refreshAccountBalance(selected.id, updated);
  }

  const currency = selected?.currency_label ?? "";

  return (
    <div className="finance-layout">
      {/* ── Account sidebar ── */}
      <aside className="finance-sidebar">
        <div className="finance-sidebar-header">
          <span className="finance-sidebar-title">Konten</span>
          <button type="button" className="btn-icon" onClick={startCreateAccount} title="Konto erstellen">＋</button>
        </div>

        {accounts.length === 0 ? (
          <p className="muted finance-empty">Noch keine Konten. Erstelle dein erstes Konto.</p>
        ) : (
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
                  {formatAmount(account.balance, account.currency_label)}
                </div>
                {account.provisional_balance > 0 ? (
                  <div className="finance-account-provisional">
                    + {formatAmount(account.provisional_balance, account.currency_label)} provisorisch
                  </div>
                ) : null}
                {account.description ? <div className="finance-account-desc">{account.description}</div> : null}
                <div className="finance-account-actions">
                  <span className="finance-account-count">{account.transaction_count} Transaktionen</span>
                  <button type="button" className="btn-icon-sm" onClick={(e) => startEditAccount(account, e)} title="Bearbeiten">✎</button>
                  <button type="button" className="btn-icon-sm btn-icon-danger" onClick={(e) => void deleteAccount(account, e)} title="Löschen">✕</button>
                </div>
              </div>
            ))}
          </div>
        )}

        {showAccountForm && (
          <div className="finance-form-overlay" onClick={() => setShowAccountForm(false)}>
            <div className="finance-form-modal" onClick={(e) => e.stopPropagation()}>
              <h3>{editingAccount ? "Konto bearbeiten" : "Neues Konto"}</h3>
              <label className="field-stack">
                <span className="field-label">Name</span>
                <input value={accountDraft.name} onChange={(e) => setAccountDraft((d) => ({ ...d, name: e.target.value }))} placeholder="z. B. Vereinskasse" autoFocus />
              </label>
              <label className="field-stack">
                <span className="field-label">Währungsbezeichnung</span>
                <input value={accountDraft.currency_label} onChange={(e) => setAccountDraft((d) => ({ ...d, currency_label: e.target.value }))} placeholder="CHF" />
              </label>
              <label className="field-stack">
                <span className="field-label">Beschreibung (optional)</span>
                <input value={accountDraft.description} onChange={(e) => setAccountDraft((d) => ({ ...d, description: e.target.value }))} placeholder="Beschreibung…" />
              </label>
              <div className="finance-form-actions">
                <button type="button" className="button-inline" onClick={() => setShowAccountForm(false)}>Abbrechen</button>
                <button type="button" className="button-inline" onClick={() => void saveAccount()} disabled={savingAccount || !accountDraft.name.trim()}>
                  {savingAccount ? "Speichern…" : "Speichern"}
                </button>
              </div>
            </div>
          </div>
        )}
      </aside>

      {/* ── Transaction panel ── */}
      <main className="finance-main">
        {!selected ? (
          <div className="finance-placeholder">
            <p className="muted">Wähle ein Konto aus der Liste, um Transaktionen anzuzeigen.</p>
          </div>
        ) : (
          <>
            <div className="finance-main-header">
              <div>
                <h2 className="finance-main-title">{selected.name}</h2>
                <div className={`finance-main-balance${selected.balance < 0 ? " finance-balance-negative" : ""}`}>
                  {formatAmount(selected.balance, selected.currency_label)}
                </div>
                {selected.provisional_balance > 0 ? (
                  <div className="finance-account-provisional">
                    + {formatAmount(selected.provisional_balance, selected.currency_label)} provisorisch ausstehend
                  </div>
                ) : null}
              </div>
              <button type="button" className="button-inline" onClick={startCreateTx}>+ Transaktion</button>
            </div>

            {showTxForm && (
              <div className="finance-tx-form">
                <div className="finance-tx-form-row">
                  <label className="field-stack finance-tx-field-amount">
                    <span className="field-label">Betrag ({currency})</span>
                    <input
                      value={txDraft.amount}
                      onChange={(e) => setTxDraft((d) => ({ ...d, amount: e.target.value }))}
                      placeholder="z. B. 50 oder -30"
                      autoFocus
                      onKeyDown={(e) => { if (e.key === "Enter") void saveTx(); if (e.key === "Escape") setShowTxForm(false); }}
                    />
                    <span className="finance-tx-hint">Positiv = Einnahme, negativ = Ausgabe</span>
                  </label>
                  <label className="field-stack finance-tx-field-desc">
                    <span className="field-label">Beschreibung</span>
                    <input
                      value={txDraft.description}
                      onChange={(e) => setTxDraft((d) => ({ ...d, description: e.target.value }))}
                      placeholder="Wofür?"
                      onKeyDown={(e) => { if (e.key === "Enter") void saveTx(); if (e.key === "Escape") setShowTxForm(false); }}
                    />
                  </label>
                  <label className="field-stack finance-tx-field-date">
                    <span className="field-label">Datum</span>
                    <DateInput value={txDraft.transaction_date} onChange={(value) => setTxDraft((d) => ({ ...d, transaction_date: value }))} />
                  </label>
                </div>
                <div className="finance-form-actions">
                  <button type="button" className="button-inline" onClick={() => { setShowTxForm(false); setEditingTx(null); }}>Abbrechen</button>
                  <button type="button" className="button-inline" onClick={() => void saveTx()} disabled={savingTx || !txDraft.description.trim() || !txDraft.amount}>
                    {savingTx ? "Speichern…" : editingTx ? "Aktualisieren" : "Hinzufügen"}
                  </button>
                </div>
              </div>
            )}

            {loadingTx ? (
              <p className="muted">Lade…</p>
            ) : transactions.length === 0 ? (
              <p className="muted finance-empty">Keine Transaktionen. Füge deine erste Transaktion hinzu.</p>
            ) : (
              <div className="finance-tx-table">
                <div className="finance-tx-header">
                  <span>Datum</span>
                  <span>Beschreibung</span>
                  <span className="finance-tx-cell-right">Betrag</span>
                  <span className="finance-tx-cell-right">Saldo</span>
                  <span></span>
                </div>
                {buildRunningBalance(transactions).map(({ tx, running }) => (
                  <div key={tx.id} className={`finance-tx-row${tx.amount < 0 ? " finance-tx-expense" : " finance-tx-income"}`}>
                    <span className="finance-tx-date">{formatDate(tx.transaction_date)}</span>
                    <span className="finance-tx-desc">
                      {tx.description}
                    </span>
                    <span className={`finance-tx-amount finance-tx-cell-right${tx.amount < 0 ? " finance-amount-neg" : " finance-amount-pos"}`}>
                      {tx.amount > 0 ? "+" : ""}{formatAmount(tx.amount, currency)}
                    </span>
                    <span className={`finance-tx-running finance-tx-cell-right${running < 0 ? " finance-balance-negative" : ""}`}>
                      {formatAmount(running, currency)}
                    </span>
                    <span className="finance-tx-actions">
                      <button type="button" className="btn-icon-sm" onClick={() => startEditTx(tx)} title="Bearbeiten">✎</button>
                      <button type="button" className="btn-icon-sm btn-icon-danger" onClick={() => void deleteTx(tx)} title="Löschen">✕</button>
                    </span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function formatAmount(amount: number, currency: string): string {
  const abs = Math.abs(amount).toFixed(2);
  const formatted = Number(abs).toLocaleString("de-CH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${amount < 0 ? "−" : ""}${formatted} ${currency}`;
}

function buildRunningBalance(transactions: FinanceTransaction[]): { tx: FinanceTransaction; running: number }[] {
  // Sorted newest first — build running balance from oldest
  const sorted = [...transactions].sort((a, b) => a.transaction_date.localeCompare(b.transaction_date) || a.id - b.id);
  let running = 0;
  const map = new Map<number, number>();
  for (const tx of sorted) {
    running += tx.amount;
    map.set(tx.id, running);
  }
  return transactions.map((tx) => ({ tx, running: map.get(tx.id) ?? 0 }));
}
