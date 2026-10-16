// Zeitraum-Regeln für Finanz- und Bussenblöcke - Gegenstück zu
// backend/app/services/protocol_period_service.py (gleiche Regeln im Editor, auf dem Handy und
// im PDF-Export).
import { useEffect, useState } from "react";

import { browserApiFetch } from "@/lib/api/client";

export type ProtocolPeriod = {
  previous_protocol_date: string | null;
  cycle_start: string | null;
  cycle_end: string | null;
};

const EMPTY_PERIOD: ProtocolPeriod = { previous_protocol_date: null, cycle_start: null, cycle_end: null };

/** Lädt Vorprotokoll-Datum und Zyklusgrenzen, sobald ein Block sie braucht. */
export function useProtocolPeriod(protocolId: string, enabled: boolean): ProtocolPeriod {
  const [period, setPeriod] = useState<ProtocolPeriod>(EMPTY_PERIOD);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    browserApiFetch<ProtocolPeriod>(`/api/protocols/${protocolId}/period`)
      .then((result) => { if (!cancelled && result) setPeriod(result); })
      .catch(() => { if (!cancelled) setPeriod(EMPTY_PERIOD); });
    return () => { cancelled = true; };
  }, [protocolId, enabled]);
  return period;
}

/** Kontostände bis und mit Stichtag (Kontostand-Blöcke «Stand am Protokolldatum»), pro Konto. */
export function useBalancesAsOf(accountIds: string[], asOf: string | null): Record<string, number> {
  const [balances, setBalances] = useState<Record<string, number>>({});
  const key = [...new Set(accountIds)].sort().join(",");
  useEffect(() => {
    if (!key || !asOf) return;
    let cancelled = false;
    for (const accountId of key.split(",")) {
      browserApiFetch<{ balance: number }>(`/api/finance/accounts/${accountId}/balance?as_of=${encodeURIComponent(asOf)}`)
        .then((result) => { if (!cancelled && result) setBalances((current) => ({ ...current, [accountId]: result.balance })); })
        .catch(() => undefined);
    }
    return () => { cancelled = true; };
  }, [key, asOf]);
  return balances;
}

type Tx = { transaction_date: string };

export function transactionMatches(tx: Tx, config: Record<string, unknown>, protocolDate: string | null, period: ProtocolPeriod): boolean {
  const filterType = String(config.finance_filter_type ?? "all");
  if (filterType === "since_last_session") return !period.previous_protocol_date || tx.transaction_date > period.previous_protocol_date;
  if (filterType === "since_date") {
    const since = String(config.finance_since_date ?? protocolDate ?? "");
    return !since || tx.transaction_date >= since;
  }
  if (filterType === "this_year") {
    const year = (protocolDate ?? new Date().toISOString()).slice(0, 4);
    return tx.transaction_date.slice(0, 4) === year;
  }
  if (filterType === "this_cycle") {
    return !period.cycle_start || (tx.transaction_date >= period.cycle_start && tx.transaction_date <= (period.cycle_end ?? tx.transaction_date));
  }
  return true;
}

/** Transaktionen eines Blocks, neueste zuerst; «letzte N» = die N neuesten. */
export function filterTransactions<T extends Tx>(txs: readonly T[], config: Record<string, unknown>, protocolDate: string | null, period: ProtocolPeriod): T[] {
  const newestFirst = [...txs].sort((left, right) => right.transaction_date.localeCompare(left.transaction_date));
  const matching = newestFirst.filter((tx) => transactionMatches(tx, config, protocolDate, period));
  return config.finance_filter_type === "last_n" ? matching.slice(0, Math.max(1, Number(config.finance_last_n ?? 10) || 10)) : matching;
}

type Fine = { account_id: string; status: string; participant_name_snapshot: string; protocol_date?: string | null };

/**
 * Optionen der Bussenliste. kind "own" = Bussen dieses Protokolls, "earlier" = offene aus
 * früheren Protokollen (Umfang «nur dieses Protokoll» blendet sie aus, «dieser Zyklus» begrenzt
 * sie auf Protokolle im Zyklus).
 */
export function filterFines<T extends Fine>(fines: readonly T[], config: Record<string, unknown>, accountId: string | null, period: ProtocolPeriod, kind: "own" | "earlier"): T[] {
  let result = [...fines];
  if (accountId) result = result.filter((fine) => fine.account_id === accountId);
  if (config.fine_list_status === "open") result = result.filter((fine) => fine.status === "pending");
  if (kind === "earlier") {
    if (config.fine_list_range === "this_protocol") result = [];
    if (config.fine_list_range === "this_cycle" && period.cycle_start) {
      result = result.filter((fine) => fine.protocol_date && fine.protocol_date >= period.cycle_start! && fine.protocol_date <= (period.cycle_end ?? fine.protocol_date));
    }
  }
  if (config.fine_list_group_by === "participant") {
    result.sort((left, right) => left.participant_name_snapshot.localeCompare(right.participant_name_snapshot, undefined, { sensitivity: "base" }));
  }
  return result;
}
