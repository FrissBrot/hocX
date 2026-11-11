"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import { StatusBanner } from "@/components/ui/status-banner";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import type { FineSplitMode, TodoFineEvaluation, TodoFineMode, TodoFineRule } from "@/types/api";

/**
 * Busse eines Todos (Pendenzen-Bussen): laufend, eingefroren oder warum keine anfällt. Wer
 * finances.manage hat, legt die Busse von Hand fest - nötig, wenn mehrere Regeln passen.
 * Speichert sofort (eigener Endpunkt, unabhängig vom Speichern des Todos).
 */
export function TodoFineSection({ todoId }: { todoId: string }) {
  const t = useTranslations("finances");
  const showToast = useToast();
  const [evaluation, setEvaluation] = useState<TodoFineEvaluation | null>(null);
  const [rules, setRules] = useState<TodoFineRule[]>([]);
  const [mode, setMode] = useState<TodoFineMode>("auto");
  const [ruleId, setRuleId] = useState("");
  const [amount, setAmount] = useState("");
  const [split, setSplit] = useState<FineSplitMode>("each");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    browserApiFetch<TodoFineEvaluation>(`/api/protocol-todos/${todoId}/fine`)
      .then((loaded) => {
        if (cancelled) return;
        apply(loaded);
        if (loaded.can_manage) {
          void browserApiFetch<TodoFineRule[]>("/api/todo-fines/rules").then((list) => { if (!cancelled) setRules(list); }).catch(() => undefined);
        }
      })
      .catch(() => { if (!cancelled) setEvaluation(null); });
    return () => { cancelled = true; };
  }, [todoId]);

  function apply(loaded: TodoFineEvaluation) {
    setEvaluation(loaded);
    setMode(loaded.fine_mode);
    setRuleId(loaded.fine_rule_id ?? loaded.matching_rules[0]?.id ?? "");
    setAmount(loaded.fine_fixed_amount != null ? String(loaded.fine_fixed_amount) : "");
    setSplit(loaded.fine_split_mode ?? "each");
  }

  async function save() {
    setSaving(true);
    try {
      const result = await browserApiFetch<TodoFineEvaluation>(`/api/protocol-todos/${todoId}/fine`, {
        method: "PUT",
        body: JSON.stringify({
          fine_mode: mode,
          fine_rule_id: mode === "rule" ? ruleId || null : null,
          fine_fixed_amount: mode === "fixed" ? Number(amount) : null,
          fine_split_mode: mode === "fixed" ? split : null,
        }),
      });
      apply(result);
      showToast(t("todoFines.todo.saved"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("todoFines.todo.saveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  if (!evaluation) return null;
  const invalid = (mode === "rule" && !ruleId) || (mode === "fixed" && (amount.trim() === "" || Number.isNaN(Number(amount)) || Number(amount) < 0));
  const changed = mode !== evaluation.fine_mode
    || (mode === "rule" && ruleId !== (evaluation.fine_rule_id ?? ""))
    || (mode === "fixed" && (Number(amount) !== evaluation.fine_fixed_amount || split !== (evaluation.fine_split_mode ?? "each")));

  return (
    <div className="field-stack todo-fine-section">
      <span className="field-label">{t("todoFines.todo.label")}</span>
      {evaluation.state === "conflict" ? (
        <StatusBanner tone="error" message={t("todoFines.todo.conflict", { rules: evaluation.matching_rules.map((rule) => rule.name).join(", ") })} />
      ) : null}
      {evaluation.state === "ok" ? (
        <div className="todo-fine-summary">
          <div className="todo-fine-summary-head">
            <Badge variant={evaluation.frozen ? "neutral" : "info"}>{evaluation.frozen ? t("todoFines.todo.frozen") : t("todoFines.todo.running")}</Badge>
            <span className="muted">
              {t("todoFines.daysLate", { count: evaluation.days_late })}
              {evaluation.rule_name ? ` · ${evaluation.rule_name}` : ` · ${t("todoFines.fixedAmount")}`}
            </span>
          </div>
          {evaluation.lines.length > 0 ? (
            <ul className="todo-fine-lines">
              {evaluation.lines.map((line, index) => (
                <li key={line.participant_id ?? index}>
                  <span>{line.participant_name}{line.tariff_name ? <span className="muted"> · {line.tariff_name}</span> : null}</span>
                  <strong>{line.amount.toFixed(2)}</strong>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : evaluation.state !== "conflict" ? (
        <span className="muted">{t(`todoFines.todo.state.${evaluation.state}`)}</span>
      ) : null}

      {evaluation.can_manage ? (
        <div className="todo-fine-settings">
          <label className="field-stack">
            <span className="field-label">{t("todoFines.todo.modeLabel")}</span>
            <Select value={mode} onChange={(event) => setMode(event.target.value as TodoFineMode)}>
              <option value="auto">{t("todoFines.todo.mode.auto")}</option>
              <option value="rule">{t("todoFines.todo.mode.rule")}</option>
              <option value="fixed">{t("todoFines.todo.mode.fixed")}</option>
              <option value="none">{t("todoFines.todo.mode.none")}</option>
            </Select>
          </label>
          {mode === "rule" ? (
            <label className="field-stack">
              <span className="field-label">{t("todoFines.todo.ruleLabel")}</span>
              <Select value={ruleId} onChange={(event) => setRuleId(event.target.value)}>
                <option value="">{t("todoFines.todo.chooseRule")}</option>
                {rules.map((rule) => <option key={rule.id} value={rule.id}>{rule.name}</option>)}
              </Select>
            </label>
          ) : null}
          {mode === "fixed" ? (
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">{t("todoFines.todo.amountLabel")}</span>
                <input type="number" min={0} step="0.05" inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} />
              </label>
              <label className="field-stack">
                <span className="field-label">{t("todoFines.splitLabel")}</span>
                <Select value={split} onChange={(event) => setSplit(event.target.value as FineSplitMode)}>
                  <option value="each">{t("todoFines.split.each")}</option>
                  <option value="split">{t("todoFines.split.split")}</option>
                </Select>
              </label>
            </div>
          ) : null}
          {changed ? (
            <div>
              <button type="button" className="button-secondary" disabled={saving || invalid} onClick={() => void save()}>
                {t("todoFines.todo.apply")}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
