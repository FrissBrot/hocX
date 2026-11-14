"use client";

import { useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Select } from "@/components/ui/select";
import { browserApiFetch } from "@/lib/api/client";
import { formatMoney } from "@/lib/utils/format";
import type { FineTariffGroup, TodoFineRule } from "@/types/api";

/** Was die Person bei Pendenzen-Bussen darf (Seite /protocols/[id] rechnet es aus). */
export type QuickTodoFineAccess = {
  /** Regeln sehen: finances.read und Modul todo_fines */
  visible: boolean;
  /** Busse festlegen: finances.manage und Modul todo_fines voll gebucht (wie im Pendenzen-Popup) */
  manage: boolean;
  currency: string;
};

export type QuickTodoFineChoice =
  | { mode: "auto" }
  | { mode: "none" }
  | { mode: "rule"; ruleId: string }
  | { mode: "fixed"; amount: string };

export type QuickRuleMatch = { rule: TodoFineRule; roleCondition: boolean };

/**
 * Regeln, die auf eine neue Schnell-Pendenz passen würden - dieselben Bedingungen wie
 * todo_fine_service.rule_matches, soweit sie vor dem Speichern bekannt sind: Tag, zugewiesene
 * Person; Aufgabenpakete gibt es hier nicht. Rollen kennt das Frontend nicht, solche Regeln
 * zählen mit Hinweis «nur für bestimmte Rollen».
 */
export function matchQuickTodoRules(rules: TodoFineRule[], tags: string[], assigneeId: string | null): QuickRuleMatch[] {
  const wanted = new Set(tags.map((tag) => tag.trim().toLowerCase()).filter(Boolean));
  return rules
    .filter((rule) => rule.is_active)
    .filter((rule) => rule.filter.tags.length === 0 || rule.filter.tags.some((tag) => wanted.has(tag.trim().toLowerCase())))
    .filter((rule) => rule.filter.task_package_ids.length === 0)
    .filter((rule) => rule.filter.participant_ids.length === 0 || (assigneeId !== null && rule.filter.participant_ids.includes(assigneeId)))
    .map((rule) => ({ rule, roleCondition: rule.filter.role_ids.length > 0 }));
}

function parseAmount(value: string): number | null {
  const trimmed = value.trim().replace(",", ".");
  if (!trimmed) return null;
  const number = Number(trimmed);
  return Number.isFinite(number) && number >= 0 ? number : null;
}

/** Einstellung für PUT /protocol-todos/{id}/fine; null = automatisch (nichts zu speichern). */
export function quickTodoFineSettings(choice: QuickTodoFineChoice) {
  if (choice.mode === "none") return { fine_mode: "none", fine_rule_id: null, fine_fixed_amount: null, fine_split_mode: null };
  if (choice.mode === "rule") return { fine_mode: "rule", fine_rule_id: choice.ruleId, fine_fixed_amount: null, fine_split_mode: null };
  if (choice.mode === "fixed") {
    const amount = parseAmount(choice.amount);
    return amount === null ? null : { fine_mode: "fixed", fine_rule_id: null, fine_fixed_amount: amount, fine_split_mode: "each" };
  }
  return null;
}

export function quickTodoFineInvalid(choice: QuickTodoFineChoice): boolean {
  return choice.mode === "fixed" && parseAmount(choice.amount) === null;
}

/**
 * Busse in «Schnelle Pendenz» (Sitzungsmenü im Protokoll-Editor): zeigt, welche Bussenregel der
 * eingegebene Tag auslöst, und lässt die Kasse die Busse gleich festlegen (automatisch, eine
 * Regel, keine Busse oder ein Fixbetrag).
 */
export function QuickTodoFine({ access, tag, assigneeId, hasDue, value, onChange }: {
  access: QuickTodoFineAccess;
  tag: string;
  assigneeId: string | null;
  hasDue: boolean;
  value: QuickTodoFineChoice;
  onChange: (choice: QuickTodoFineChoice) => void;
}) {
  const t = useTranslations("protocols.sessionPanel.fine");
  const tFines = useTranslations("finances.todoFines.todo.v2");
  const locale = useLocale();
  const [rules, setRules] = useState<TodoFineRule[] | null>(null);
  const [tariffs, setTariffs] = useState<FineTariffGroup[]>([]);

  useEffect(() => {
    if (!access.visible) return;
    let cancelled = false;
    Promise.all([
      browserApiFetch<TodoFineRule[]>("/api/todo-fines/rules"),
      browserApiFetch<FineTariffGroup[]>("/api/todo-fines/tariffs").catch(() => [] as FineTariffGroup[]),
    ])
      .then(([ruleList, tariffList]) => { if (!cancelled) { setRules(ruleList); setTariffs(tariffList); } })
      // Ohne Regeln bleibt der Block einfach leer, das Erfassen geht weiter
      .catch(() => { if (!cancelled) setRules([]); });
    return () => { cancelled = true; };
  }, [access.visible]);

  const matches = useMemo(() => matchQuickTodoRules(rules ?? [], [tag], assigneeId), [rules, tag, assigneeId]);
  if (!access.visible || rules === null) return null;
  if (!access.manage && matches.length === 0) return null;

  const money = (amount: number) => formatMoney(amount, access.currency, locale, { currencyFirst: true });
  const defaultTariff = tariffs.find((tariff) => tariff.is_default) ?? tariffs[0];
  function rate(rule: TodoFineRule): string {
    const item = rule.rates.find((entry) => entry.tariff_group_id === defaultTariff?.id) ?? rule.rates[0];
    const base = Number(item?.base_amount ?? 0);
    const per = Number(item?.interval_amount ?? 0);
    if (per > 0) {
      return base > 0
        ? tFines("rateBoth", { base: money(base), amount: formatMoney(per, "", locale), days: rule.interval_days })
        : tFines("ratePer", { amount: money(per), days: rule.interval_days });
    }
    return tFines("rateOnce", { base: money(base) });
  }

  const automatic = value.mode === "auto";
  const selectValue = value.mode === "rule" ? `rule:${value.ruleId}` : value.mode;
  const invalid = quickTodoFineInvalid(value);

  return (
    <div className="quick-todo-fine">
      {automatic && matches.length === 1 ? (
        <div className="quick-todo-fine-hint">
          <strong>{t("ruleApplies", { name: matches[0].rule.name })}</strong>
          <span>{rate(matches[0].rule)}{matches[0].roleCondition ? ` · ${t("roleCondition")}` : ""}</span>
          {!hasDue ? <span className="quick-todo-fine-muted">{t("noDue")}</span> : null}
        </div>
      ) : automatic && matches.length > 1 ? (
        <div className="quick-todo-fine-hint quick-todo-fine-hint-warning">
          <strong>{t("conflict", { count: matches.length })}</strong>
          <span>{matches.map((match) => match.rule.name).join(", ")}</span>
        </div>
      ) : null}

      {access.manage ? (
        <div className="quick-todo-fine-row">
          <Select
            className="session-panel-input session-panel-input-sm quick-todo-fine-select"
            aria-label={t("label")}
            value={selectValue}
            onChange={(event) => {
              const next = event.target.value;
              if (next === "auto" || next === "none") onChange({ mode: next });
              else if (next === "fixed") onChange({ mode: "fixed", amount: "" });
              else onChange({ mode: "rule", ruleId: next.slice("rule:".length) });
            }}
          >
            <option value="auto">{t("choiceAuto")}</option>
            <option value="fixed">{t("choiceFixed")}</option>
            {(rules ?? []).filter((rule) => rule.is_active).map((rule) => (
              <option key={rule.id} value={`rule:${rule.id}`}>{t("choiceRule", { name: rule.name })}</option>
            ))}
            <option value="none">{t("choiceNone")}</option>
          </Select>
          {value.mode === "fixed" ? (
            <label className={`quick-todo-fine-amount${invalid && value.amount ? " quick-todo-fine-amount-invalid" : ""}`}>
              <span>{access.currency}</span>
              <input
                value={value.amount}
                inputMode="decimal"
                aria-label={t("amountLabel")}
                placeholder="0.00" // i18n-ok: Zahlenformat
                onChange={(event) => onChange({ mode: "fixed", amount: event.target.value.replace(/[^0-9.,]/g, "") })}
              />
            </label>
          ) : null}
        </div>
      ) : null}
      {(value.mode === "rule" || value.mode === "fixed") && !hasDue ? <span className="quick-todo-fine-muted">{t("noDue")}</span> : null}
    </div>
  );
}
