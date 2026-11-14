import { describe, expect, it } from "vitest";

import type { TodoFineRule } from "@/types/api";

import { matchQuickTodoRules, quickTodoFineInvalid, quickTodoFineSettings } from "./quick-todo-fine";

function rule(name: string, filter: Partial<TodoFineRule["filter"]> = {}, isActive = true): TodoFineRule {
  return {
    id: `id-${name}`, name, sort_index: 0, is_active: isActive, applies_from: "2020-01-01", interval_days: 1, split_mode: "each", account_id: null,
    filter: { tags: [], task_package_ids: [], participant_ids: [], role_ids: [], ...filter },
    rates: [],
  };
}

describe("matchQuickTodoRules", () => {
  const rules = [
    rule("Material", { tags: ["Material"] }),
    rule("Alle"),
    rule("Inaktiv", { tags: ["material"] }, false),
    rule("Paket", { task_package_ids: ["p1"] }),
    rule("Nur Anna", { tags: ["material"], participant_ids: ["anna"] }),
    rule("Vorstand", { tags: ["material"], role_ids: ["r1"] }),
  ];

  it("passt Tags ohne Gross-/Kleinschreibung und lässt inaktive und Paket-Regeln weg", () => {
    const names = matchQuickTodoRules(rules, [" MATERIAL "], null).map((match) => match.rule.name);
    expect(names).toEqual(["Material", "Alle", "Vorstand"]);
  });

  it("Personen-Filter greift erst mit zugewiesener Person, Rollen nur als Hinweis", () => {
    const matches = matchQuickTodoRules(rules, ["material"], "anna");
    expect(matches.map((match) => match.rule.name)).toContain("Nur Anna");
    expect(matches.find((match) => match.rule.name === "Vorstand")?.roleCondition).toBe(true);
    expect(matchQuickTodoRules([rules[0]], ["Sitzungsnotizen"], null)).toEqual([]);
  });
});

describe("quickTodoFineSettings", () => {
  it("speichert nur, was von «automatisch» abweicht", () => {
    expect(quickTodoFineSettings({ mode: "auto" })).toBeNull();
    expect(quickTodoFineSettings({ mode: "none" })).toMatchObject({ fine_mode: "none" });
    expect(quickTodoFineSettings({ mode: "rule", ruleId: "r" })).toMatchObject({ fine_mode: "rule", fine_rule_id: "r" });
    expect(quickTodoFineSettings({ mode: "fixed", amount: "12,50" })).toMatchObject({ fine_mode: "fixed", fine_fixed_amount: 12.5, fine_split_mode: "each" });
  });

  it("ein leerer oder ungültiger Fixbetrag sperrt das Erstellen", () => {
    expect(quickTodoFineInvalid({ mode: "fixed", amount: "" })).toBe(true);
    expect(quickTodoFineInvalid({ mode: "fixed", amount: "5" })).toBe(false);
    expect(quickTodoFineInvalid({ mode: "auto" })).toBe(false);
  });
});
