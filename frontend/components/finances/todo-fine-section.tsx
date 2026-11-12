"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { HelpPopover } from "@/components/ui/help-popover";
import { Select } from "@/components/ui/select";
import { StatusBanner } from "@/components/ui/status-banner";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatRappen } from "@/lib/utils/format";
import type { FineSplitMode, TodoFineEvaluation, TodoFineMode, TodoFineRule } from "@/types/api";

/**
 * Busse eines Todos (Pendenzen-Bussen): laufend, eingefroren oder warum keine anfällt. Wer
 * finances.manage hat, legt die Busse von Hand fest - nötig, wenn mehrere Regeln passen.
 * Speichert sofort (eigener Endpunkt, unabhängig vom Speichern des Todos) - darum als eigener
 * Kasten mit eigenem Hinweis. `readOnly`: nur anzeigen (mobiles Sheet).
 */
export function TodoFineSection({ todoId, readOnly = false }: { todoId: string; readOnly?: boolean }) {
  const t = useTranslations("finances");
  const locale = useLocale();
  const [loadFailed, setLoadFailed] = useState(false);
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
        if (loaded.can_manage && !readOnly) {
          void browserApiFetch<TodoFineRule[]>("/api/todo-fines/rules")
            .then((list) => { if (!cancelled) setRules(list); })
            .catch(() => { if (!cancelled) showToast(t("todoFines.todo.rulesLoadFailed"), "error"); });
        }
      })
      .catch(() => { if (!cancelled) { setEvaluation(null); setLoadFailed(true); } });
    return () => { cancelled = true; };
    // showToast/t bewusst nicht als Abhängigkeit: nur beim Öffnen einer Pendenz laden
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [todoId, readOnly]);

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

  if (!evaluation) {
    return loadFailed ? (
      <div className="field-stack todo-fine-section">
        <span className="field-label">{t("todoFines.todo.label")}</span>
        <StatusBanner tone="error" message={t("todoFines.todo.loadFailed")} />
      </div>
    ) : null;
  }
  const invalid = (mode === "rule" && !ruleId) || (mode === "fixed" && (amount.trim() === "" || Number.isNaN(Number(amount)) || Number(amount) < 0));
  const changed = mode !== evaluation.fine_mode
    || (mode === "rule" && ruleId !== (evaluation.fine_rule_id ?? ""))
    || (mode === "fixed" && (Number(amount) !== evaluation.fine_fixed_amount || split !== (evaluation.fine_split_mode ?? "each")));

  return (
    <div className="field-stack todo-fine-section">
      <span className="field-label">
        {t("todoFines.todo.label")}{" "}
        <HelpPopover topic={t("todoFines.todo.label")} docs={{ page: "bussen", anchor: evaluation.state === "conflict" ? "konflikt" : "einfrieren" }}>
          {evaluation.state === "conflict" ? t("todoFines.help.conflict") : t("todoFines.help.todoFine")}
        </HelpPopover>
      </span>
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
                  <strong>{formatRappen(Math.round(Number(line.amount) * 100), locale)}</strong>
                </li>
              ))}
            </ul>
          ) : null}
          {evaluation.frozen ? <span className="field-help">{t("todoFines.todo.frozenHint")}</span> : null}
          {evaluation.running ? <span className="field-help">{t("todoFines.todo.runningHint")}</span> : null}
        </div>
      ) : evaluation.state !== "conflict" ? (
        <span className="muted">{t(`todoFines.todo.state.${evaluation.state}`)}</span>
      ) : null}

      {evaluation.can_manage && !readOnly ? (
        <div className="todo-fine-settings">
          {/* div statt label: der «?»-Knopf darf nicht zum Bedienelement des Labels werden */}
          <div className="field-stack">
            <span className="field-label">
              {t("todoFines.todo.modeLabel")}{" "}
              <HelpPopover topic={t("todoFines.todo.modeLabel")} docs={{ page: "bussen", anchor: "von-hand" }}>{t("todoFines.help.mode")}</HelpPopover>
            </span>
            <Select aria-label={t("todoFines.todo.modeLabel")} value={mode} onChange={(event) => setMode(event.target.value as TodoFineMode)}>
              <option value="auto">{t("todoFines.todo.mode.auto")}</option>
              <option value="rule">{t("todoFines.todo.mode.rule")}</option>
              <option value="fixed">{t("todoFines.todo.mode.fixed")}</option>
              <option value="none">{t("todoFines.todo.mode.none")}</option>
            </Select>
          </div>
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
            <div className="field-stack">
              <div>
                <button type="button" className="button-secondary" disabled={saving || invalid} onClick={() => void save()}>
                  {t("todoFines.todo.apply")}
                </button>
              </div>
              <span className="field-help">{invalid ? t("todoFines.todo.applyInvalid") : t("todoFines.todo.applyHint")}</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
