import { describe, expect, it } from "vitest";
import { filterFines, filterTransactions } from "./period";

const period = { previous_protocol_date: "2026-03-01", cycle_start: "2025-08-01", cycle_end: "2026-07-31" };
const txs = [
  { id: "1", transaction_date: "2025-06-01" },
  { id: "2", transaction_date: "2025-09-01" },
  { id: "3", transaction_date: "2026-03-01" },
  { id: "4", transaction_date: "2026-03-15" },
];
const ids = (list: { id: string }[]) => list.map((tx) => tx.id);

describe("filterTransactions (gleiche Regeln wie protocol_period_service.py)", () => {
  it("seit letzter Sitzung: nach dem Datum des vorherigen Protokolls", () => {
    expect(ids(filterTransactions(txs, { finance_filter_type: "since_last_session" }, "2026-04-01", period))).toEqual(["4"]);
  });
  it("dieser Zyklus und dieses Jahr (bezogen aufs Protokolldatum)", () => {
    expect(ids(filterTransactions(txs, { finance_filter_type: "this_cycle" }, "2026-04-01", period))).toEqual(["4", "3", "2"]);
    expect(ids(filterTransactions(txs, { finance_filter_type: "this_year" }, "2025-12-01", period))).toEqual(["2", "1"]);
  });
  it("seit Datum und letzte N", () => {
    expect(ids(filterTransactions(txs, { finance_filter_type: "since_date", finance_since_date: "2026-01-01" }, null, period))).toEqual(["4", "3"]);
    expect(ids(filterTransactions(txs, { finance_filter_type: "last_n", finance_last_n: 2 }, null, period))).toEqual(["4", "3"]);
  });
});

describe("filterFines", () => {
  const fines = [
    { id: "a", account_id: "k1", status: "pending", participant_name_snapshot: "Zora", protocol_date: "2025-05-01" },
    { id: "b", account_id: "k1", status: "collected", participant_name_snapshot: "Anna", protocol_date: "2025-10-01" },
    { id: "c", account_id: "k2", status: "pending", participant_name_snapshot: "Ben", protocol_date: "2026-01-01" },
  ];
  it("Konto, nur offene, nach Person", () => {
    expect(ids(filterFines(fines, { fine_list_status: "open", fine_list_group_by: "participant" }, null, period, "own"))).toEqual(["c", "a"]);
    expect(ids(filterFines(fines, {}, "k1", period, "own"))).toEqual(["a", "b"]);
  });
  it("Umfang für frühere Bussen", () => {
    expect(filterFines(fines, { fine_list_range: "this_protocol" }, null, period, "earlier")).toEqual([]);
    expect(ids(filterFines(fines, { fine_list_range: "this_cycle" }, null, period, "earlier"))).toEqual(["b", "c"]);
  });
});
