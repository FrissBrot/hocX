import { describe, expect, it } from "vitest";

import { applyRuleTemplate, hasAdvancedSettings, ruleAmount } from "@/components/finances/todo-fine-rules";
import { runningFineTodoIds } from "@/components/todos/use-running-todo-fines";
import type { TodoFineListItem } from "@/types/api";

describe("Regel-Vorlagen (Pendenzen-Bussen)", () => {
  const draft = { interval_days: "3", rates: { a: { base: "9", interval: "" } } };

  it("«Fixbetrag pro Tag» setzt Intervall 1 und denselben Betrag für alle Tarife", () => {
    const next = applyRuleTemplate(draft, "perDay", ["a", "b"]);
    expect(next.interval_days).toBe("1");
    expect(next.rates).toEqual({ a: { base: "", interval: "1.00" }, b: { base: "", interval: "1.00" } });
    expect(ruleAmount(0, 1, 1, 3)).toBe(3);
  });

  it("«Grundbetrag + pro Woche» rechnet Grundbetrag ab Tag 1 plus Zuschlag je volle Woche", () => {
    const next = applyRuleTemplate(draft, "basePlusWeek", ["a"]);
    expect(next.interval_days).toBe("7");
    const rate = next.rates.a;
    expect(ruleAmount(Number(rate.base), Number(rate.interval), 7, 1)).toBe(5);
    expect(ruleAmount(Number(rate.base), Number(rate.interval), 7, 14)).toBe(15);
  });

  it("klappt «Erweitert» nur auf, wenn Filter oder Konto gesetzt sind", () => {
    const empty = { account_id: "", tags: [], task_package_ids: [], participant_ids: [], role_ids: [] };
    expect(hasAdvancedSettings(empty)).toBe(false);
    expect(hasAdvancedSettings({ ...empty, tags: ["Ämtli"] })).toBe(true);
    expect(hasAdvancedSettings({ ...empty, account_id: "acc" })).toBe(true);
  });
});

describe("Badge «Busse läuft»", () => {
  it("nimmt nur laufende Bussen, nicht eingefrorene oder Konflikte", () => {
    const item = (status: TodoFineListItem["status"], todo_id: string | null) => ({ status, todo_id }) as TodoFineListItem;
    const ids = runningFineTodoIds([item("running", "t1"), item("pending", "t2"), item("conflict", "t3"), item("running", null)]);
    expect([...ids]).toEqual(["t1"]);
  });
});
