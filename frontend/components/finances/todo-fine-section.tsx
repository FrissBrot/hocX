"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { HelpPopover } from "@/components/ui/help-popover";
import { usePopoverDismiss, usePopoverPosition } from "@/components/ui/popover";
import { StatusBanner } from "@/components/ui/status-banner";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatMoney } from "@/lib/utils/format";
import type { FineSplitMode, FineTariffGroup, TodoFineEvaluation, TodoFineMode, TodoFineRule } from "@/types/api";

/** Einstellung der Busse an einer Pendenz (PUT /protocol-todos/{id}/fine). */
export type TodoFineDraft = {
  fine_mode: TodoFineMode;
  fine_rule_id: string | null;
  fine_fixed_amount: number | null;
  fine_split_mode: FineSplitMode | null;
};

type Draft = { mode: TodoFineMode; ruleId: string | null; amount: string; split: FineSplitMode };

const PREVIEW_DEBOUNCE_MS = 250;

function parseAmount(value: string): number | null {
  const trimmed = value.trim().replace(",", ".");
  if (!trimmed) return null;
  const number = Number(trimmed);
  return Number.isFinite(number) && number >= 0 ? number : null;
}

function toSettings(draft: Draft): TodoFineDraft | null {
  if (draft.amount.trim() !== "") {
    const amount = parseAmount(draft.amount);
    return amount === null ? null : { fine_mode: "fixed", fine_rule_id: null, fine_fixed_amount: amount, fine_split_mode: draft.split };
  }
  if (draft.mode === "rule") return draft.ruleId ? { fine_mode: "rule", fine_rule_id: draft.ruleId, fine_fixed_amount: null, fine_split_mode: null } : null;
  if (draft.mode === "none") return { fine_mode: "none", fine_rule_id: null, fine_fixed_amount: null, fine_split_mode: null };
  return { fine_mode: "auto", fine_rule_id: null, fine_fixed_amount: null, fine_split_mode: null };
}

function fromEvaluation(loaded: TodoFineEvaluation): Draft {
  return {
    mode: loaded.fine_mode === "fixed" ? "auto" : loaded.fine_mode,
    ruleId: loaded.fine_rule_id,
    amount: loaded.fine_mode === "fixed" && loaded.fine_fixed_amount != null ? String(loaded.fine_fixed_amount) : "",
    split: loaded.fine_split_mode ?? "each",
  };
}

function sameSettings(a: TodoFineDraft | null, b: TodoFineDraft | null): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Busse einer Pendenz (Design «hocX Todo Busse», Busse v2): Fixbetrag (optional), Regel-Zeile mit
 * «Automatisch», einer fest zugewiesenen Regel (auch wenn ihre Filter nicht passen) oder «Keine
 * Busse», darunter die Beträge je Person mit Tarif. Ein Fixbetrag geht vor.
 *
 * - Ohne finances.manage oder `readOnly` (mobiles Sheet): nur anzeigen.
 * - Mit `onDraftChange` (Pendenzen-Popup): die Einstellung speichert das Popup mit «Speichern».
 * - Ohne `onDraftChange` (Konflikt auflösen auf /fines): eigener Knopf «Übernehmen».
 */
export function TodoFineSection({ todoId, readOnly = false, assigneeCount, onDraftChange }: {
  todoId: string;
  readOnly?: boolean;
  /** Zahl der Verantwortlichen im Formular (für «Je Person / Aufteilen» beim Fixbetrag). */
  assigneeCount?: number;
  onDraftChange?: (settings: TodoFineDraft | null) => void;
}) {
  const t = useTranslations("finances");
  const locale = useLocale();
  const showToast = useToast();
  const [loadFailed, setLoadFailed] = useState(false);
  const [evaluation, setEvaluation] = useState<TodoFineEvaluation | null>(null);
  const [preview, setPreview] = useState<TodoFineEvaluation | null>(null);
  const [rules, setRules] = useState<TodoFineRule[]>([]);
  const [tariffs, setTariffs] = useState<FineTariffGroup[]>([]);
  const [draft, setDraft] = useState<Draft>({ mode: "auto", ruleId: null, amount: "", split: "each" });
  const [ruleTotals, setRuleTotals] = useState<Record<string, number>>({});
  const [menuOpen, setMenuOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const anchorRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const menuStyle = usePopoverPosition(menuOpen, anchorRef, "start", 6, { estimatedHeight: 360 });
  usePopoverDismiss(menuOpen, () => setMenuOpen(false), [anchorRef, panelRef]);

  useEffect(() => {
    let cancelled = false;
    browserApiFetch<TodoFineEvaluation>(`/api/protocol-todos/${todoId}/fine`)
      .then((loaded) => {
        if (cancelled) return;
        setEvaluation(loaded);
        setDraft(fromEvaluation(loaded));
        if (loaded.can_manage && !readOnly) {
          Promise.all([
            browserApiFetch<TodoFineRule[]>("/api/todo-fines/rules"),
            browserApiFetch<FineTariffGroup[]>("/api/todo-fines/tariffs").catch(() => [] as FineTariffGroup[]),
          ])
            .then(([ruleList, tariffList]) => { if (!cancelled) { setRules(ruleList); setTariffs(tariffList); } })
            .catch(() => { if (!cancelled) showToast(t("todoFines.todo.rulesLoadFailed"), "error"); });
        }
      })
      .catch(() => { if (!cancelled) { setEvaluation(null); setLoadFailed(true); } });
    return () => { cancelled = true; };
    // showToast/t bewusst nicht als Abhängigkeit: nur beim Öffnen einer Pendenz laden
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [todoId, readOnly]);

  const manage = Boolean(evaluation?.can_manage) && !readOnly;
  const savedSettings = useMemo(() => (evaluation ? toSettings(fromEvaluation(evaluation)) : null), [evaluation]);
  const settings = toSettings(draft);
  const changed = manage && !sameSettings(settings, savedSettings);
  const settingsKey = JSON.stringify(settings);

  // Das Popup speichert die Einstellung mit «Speichern»: geänderte Einstellung melden (null = unverändert)
  useEffect(() => {
    if (!onDraftChange || !manage) return;
    onDraftChange(changed ? settings : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settingsKey, changed, manage]);

  // Vorschau der noch nicht gespeicherten Einstellung
  useEffect(() => {
    if (!changed || !settings) {
      setPreview(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      browserApiFetch<TodoFineEvaluation>(`/api/protocol-todos/${todoId}/fine/preview`, { method: "POST", body: settingsKey, signal: controller.signal })
        .then((result) => setPreview(result))
        .catch(() => { if (!controller.signal.aborted) setPreview(null); });
    }, PREVIEW_DEBOUNCE_MS);
    return () => { window.clearTimeout(timer); controller.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settingsKey, changed, todoId]);

  const shown = changed ? preview ?? null : evaluation;
  const conflictRules = shown?.state === "conflict" ? shown.matching_rules : [];
  const conflictKey = conflictRules.map((rule) => rule.id).join(",");

  // Konflikt: Total je passender Regel zeigen (Vorschau je Regel)
  useEffect(() => {
    if (!manage || !conflictKey) return;
    let cancelled = false;
    for (const rule of conflictRules) {
      if (ruleTotals[rule.id] !== undefined) continue;
      browserApiFetch<TodoFineEvaluation>(`/api/protocol-todos/${todoId}/fine/preview`, {
        method: "POST",
        body: JSON.stringify({ fine_mode: "rule", fine_rule_id: rule.id, fine_fixed_amount: null, fine_split_mode: null }),
      })
        .then((result) => { if (!cancelled) setRuleTotals((current) => ({ ...current, [rule.id]: Number(result.total) })); })
        .catch(() => undefined);
    }
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conflictKey, manage, todoId]);

  async function apply() {
    if (!settings) return;
    setSaving(true);
    try {
      const result = await browserApiFetch<TodoFineEvaluation>(`/api/protocol-todos/${todoId}/fine`, { method: "PUT", body: JSON.stringify(settings) });
      setEvaluation(result);
      setDraft(fromEvaluation(result));
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

  const currency = evaluation.currency ?? "";
  const money = (value: number) => formatMoney(Number(value), currency, locale, { currencyFirst: true });
  const label = (
    <span className="field-label">
      {t("todoFines.todo.label")}{" "}
      <HelpPopover topic={t("todoFines.todo.label")} docs={{ page: "bussen", anchor: evaluation.state === "conflict" ? "konflikt" : "einfrieren" }}>
        {evaluation.state === "conflict" ? t("todoFines.help.conflict") : t("todoFines.help.todoFine")}
      </HelpPopover>
    </span>
  );
  const lines = (current: TodoFineEvaluation, fixed: boolean) =>
    current.lines.length > 0 ? (
      <div className="todo-fine-lines-box">
        <ul className="todo-fine-lines">
          {current.lines.map((line, index) => (
            <li key={line.participant_id ?? index}>
              <span>
                <strong>{line.participant_name}</strong>
                <span className="muted"> · {line.tariff_name ?? (fixed ? (current.split_mode === "split" ? t("todoFines.todo.v2.share") : t("todoFines.todo.v2.fixed")) : t("todoFines.todo.v2.defaultTariff"))}</span>
              </span>
              <strong>{money(line.amount)}</strong>
            </li>
          ))}
        </ul>
        <div className="todo-fine-total">
          <span className="muted">{fixed || current.frozen ? t("todoFines.todo.v2.total") : t("todoFines.todo.v2.totalToday")}</span>
          <strong>{money(current.total)}</strong>
        </div>
      </div>
    ) : null;

  // Nur anzeigen (ohne finances.manage oder mobil)
  if (!manage) {
    return (
      <div className="field-stack todo-fine-section">
        {label}
        {evaluation.state === "conflict" ? (
          <StatusBanner tone="error" message={t("todoFines.todo.conflict", { rules: evaluation.matching_rules.map((rule) => rule.name).join(", ") })} />
        ) : null}
        {evaluation.state === "ok" ? (
          <>
            <div className="todo-fine-summary-head">
              <Badge variant={evaluation.frozen ? "neutral" : "info"}>{evaluation.frozen ? t("todoFines.todo.frozen") : t("todoFines.todo.running")}</Badge>
              <span className="muted">
                {t("todoFines.daysLate", { count: evaluation.days_late })}
                {evaluation.rule_name ? ` · ${evaluation.rule_name}` : ` · ${t("todoFines.fixedAmount")}`}
              </span>
            </div>
            {lines(evaluation, evaluation.fine_mode === "fixed")}
            {evaluation.frozen ? <span className="field-help">{t("todoFines.todo.frozenHint")}</span> : null}
            {evaluation.running ? <span className="field-help">{t("todoFines.todo.runningHint")}</span> : null}
          </>
        ) : evaluation.state !== "conflict" ? (
          <span className="muted">{t(`todoFines.todo.state.${evaluation.state}`)}</span>
        ) : null}
      </div>
    );
  }

  // ── Kasse: Busse v2 ──
  const hasAmount = draft.amount.trim() !== "";
  const amountInvalid = hasAmount && parseAmount(draft.amount) === null;
  const autoRules = evaluation.auto_rules ?? [];
  const kind: "fixed" | "none" | "rule" | "auto" = hasAmount ? "fixed" : draft.mode === "none" ? "none" : draft.mode === "rule" ? "rule" : "auto";
  const selectedRule = rules.find((rule) => rule.id === draft.ruleId) ?? null;
  const autoState = kind === "auto" ? shown?.state ?? evaluation.state : null;
  const defaultTariff = tariffs.find((tariff) => tariff.is_default) ?? tariffs[0];
  const people = assigneeCount ?? evaluation.lines.length;

  function describeRule(rule: TodoFineRule): string {
    const rate = rule.rates.find((item) => item.tariff_group_id === defaultTariff?.id) ?? rule.rates[0];
    const base = Number(rate?.base_amount ?? 0);
    const per = Number(rate?.interval_amount ?? 0);
    const amount = per > 0
      ? base > 0
        ? t("todoFines.todo.v2.rateBoth", { base: money(base), amount: formatMoney(per, "", locale), days: rule.interval_days })
        : t("todoFines.todo.v2.ratePer", { amount: money(per), days: rule.interval_days })
      : t("todoFines.todo.v2.rateOnce", { base: money(base) });
    const filter = rule.filter.tags.length
      ? rule.filter.tags.map((tag) => `«${tag}»`).join(", ")
      : rule.filter.task_package_ids.length || rule.filter.participant_ids.length || rule.filter.role_ids.length
        ? t("todoFines.todo.v2.filtered")
        : t("todoFines.todo.v2.allTodos");
    return `${amount} · ${filter}`;
  }

  const pick = (patch: Partial<Draft>) => {
    setDraft((current) => ({ ...current, amount: "", ...patch }));
    setMenuOpen(false);
  };

  const kicker = kind === "fixed" ? t("todoFines.todo.v2.kickerRule")
    : kind === "none" ? t("todoFines.todo.v2.kickerException")
    : kind === "rule" ? t("todoFines.todo.v2.kickerFixedRule")
    : t("todoFines.todo.v2.kickerAuto");
  const buttonLabel = kind === "fixed" ? t("todoFines.todo.v2.overridden")
    : kind === "none" ? t("todoFines.todo.mode.none")
    : kind === "rule" ? selectedRule?.name ?? shown?.rule_name ?? evaluation.rule_name ?? t("todoFines.todo.chooseRule")
    : autoState === "conflict" ? t("todoFines.todo.v2.rulesMatch", { count: (shown ?? evaluation).matching_rules.length })
    : autoRules.length === 1 ? autoRules[0].name
    : autoRules.length > 1 ? t("todoFines.todo.v2.rulesMatch", { count: autoRules.length })
    : t("todoFines.todo.v2.noRuleMatches");
  const ruleMatches = Boolean(draft.ruleId && autoRules.some((rule) => rule.id === draft.ruleId));
  const footnote = kind === "fixed" ? t("todoFines.todo.v2.noteFixed")
    : kind === "none" ? t("todoFines.todo.v2.noteNone")
    : kind === "rule" ? (ruleMatches ? t("todoFines.todo.v2.noteRule") : t("todoFines.todo.v2.noteRuleForced"))
    : autoState === "conflict" ? t("todoFines.todo.v2.noteConflict")
    : autoState === "ok" ? t("todoFines.todo.v2.noteAuto")
    : autoState === "no_rule" ? t("todoFines.todo.v2.noteNoRule")
    : null;
  // Gründe ohne Busse (nicht verspätet, ohne Fälligkeit …) bleiben sichtbar
  const stateNote = shown && !["ok", "conflict", "none"].includes(shown.state) && !(kind === "auto" && shown.state === "no_rule")
    ? t(`todoFines.todo.state.${shown.state}`)
    : null;
  const autoSub = autoRules.length === 1 ? t("todoFines.todo.v2.autoMatchOne", { name: autoRules[0].name })
    : autoRules.length > 1 ? t("todoFines.todo.v2.rulesMatch", { count: autoRules.length })
    : t("todoFines.todo.v2.noRuleMatches");

  const menuItem = (key: string, selected: boolean, title: string, sub: string, onSelect: () => void, matches = false) => (
    <button key={key} type="button" role="menuitemradio" aria-checked={selected} className={`todo-fine-menu-item${selected ? " todo-fine-menu-item-selected" : ""}`} onClick={onSelect}>
      <span className="todo-fine-menu-text">
        <span className="todo-fine-menu-title">{title}</span>
        <span className="todo-fine-menu-sub">{sub}</span>
      </span>
      <span className="todo-fine-menu-meta">
        {matches ? <Badge variant="success">{t("todoFines.todo.v2.matches")}</Badge> : null}
        <span className="todo-fine-menu-check" aria-hidden="true">{selected ? "✓" : ""}</span>
      </span>
    </button>
  );

  return (
    <div className="field-stack todo-fine-section todo-fine-v2">
      <div className="todo-fine-head">
        {label}
        {shown?.running && (kind === "auto" || kind === "rule") ? (
          <Badge variant="info">{t("todoFines.todo.v2.runningDays", { count: shown.days_late })}</Badge>
        ) : shown?.frozen ? <Badge variant="neutral">{t("todoFines.todo.frozen")}</Badge> : null}
      </div>

      <label className={`todo-fine-amount${amountInvalid ? " todo-fine-amount-invalid" : ""}`}>
        {currency ? <span className="todo-fine-amount-currency">{currency}</span> : null}
        <input
          value={draft.amount}
          inputMode="decimal"
          aria-label={t("todoFines.todo.v2.amountLabel")}
          placeholder={kind === "fixed" ? "" : t("todoFines.todo.v2.amountPlaceholder")}
          onChange={(event) => { setDraft((current) => ({ ...current, amount: event.target.value.replace(/[^0-9.,]/g, "") })); setMenuOpen(false); }}
        />
        {hasAmount ? (
          <button type="button" className="button-icon-soft button-icon-soft-sm" aria-label={t("todoFines.todo.v2.clearAmount")} onClick={() => setDraft((current) => ({ ...current, amount: "" }))}>✕</button>
        ) : null}
      </label>

      {hasAmount && people > 1 ? (
        <div className="todo-fine-split" role="radiogroup" aria-label={t("todoFines.splitLabel")}>
          {(["each", "split"] as FineSplitMode[]).map((value) => (
            <button key={value} type="button" role="radio" aria-checked={draft.split === value} className={draft.split === value ? "todo-fine-split-active" : ""} onClick={() => setDraft((current) => ({ ...current, split: value }))}>
              {value === "each" ? t("todoFines.todo.v2.splitEach") : t("todoFines.todo.v2.splitShare")}
            </button>
          ))}
        </div>
      ) : null}

      <button
        ref={anchorRef}
        type="button"
        className={`todo-fine-rule-button${kind === "fixed" ? " todo-fine-rule-button-muted" : ""}${autoState === "conflict" ? " todo-fine-rule-button-conflict" : ""}`}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onClick={() => setMenuOpen((open) => !open)}
      >
        <span className="todo-fine-rule-text">
          <span className="todo-fine-rule-kicker">{kicker}</span>
          <span className="todo-fine-rule-label">{buttonLabel}</span>
        </span>
        <span className="todo-fine-rule-caret" aria-hidden="true">▾</span>
      </button>
      {menuOpen && typeof document !== "undefined"
        ? createPortal(
            <div ref={panelRef} role="menu" aria-label={t("todoFines.todo.v2.ruleMenu")} className="popover-panel todo-fine-menu" style={menuStyle}>
              {menuItem("auto", !hasAmount && draft.mode === "auto", t("todoFines.todo.v2.auto"), autoSub, () => pick({ mode: "auto", ruleId: null }))}
              <div className="todo-fine-menu-divider">{t("todoFines.todo.v2.assignRule")}</div>
              {rules.map((rule) =>
                menuItem(rule.id, !hasAmount && draft.mode === "rule" && draft.ruleId === rule.id, rule.name, describeRule(rule), () => pick({ mode: "rule", ruleId: rule.id }), autoRules.some((item) => item.id === rule.id))
              )}
              <div className="todo-fine-menu-divider">{t("todoFines.todo.v2.exception")}</div>
              {menuItem("none", !hasAmount && draft.mode === "none", t("todoFines.todo.mode.none"), t("todoFines.todo.v2.noneSub"), () => pick({ mode: "none", ruleId: null }))}
            </div>,
            document.body
          )
        : null}

      {autoState === "conflict" ? (
        <div className="todo-fine-conflict">
          <div className="todo-fine-conflict-text">{t("todoFines.todo.v2.conflictText")}</div>
          {(shown ?? evaluation).matching_rules.map((rule) => (
            <button key={rule.id} type="button" className="todo-fine-conflict-rule" onClick={() => pick({ mode: "rule", ruleId: rule.id })}>
              <span>{rule.name}</span>
              <strong>{ruleTotals[rule.id] !== undefined ? money(ruleTotals[rule.id]) : "…"}</strong>
            </button>
          ))}
        </div>
      ) : null}

      {shown && shown.state === "ok" ? lines(shown, kind === "fixed") : null}
      {stateNote ? <span className="field-help">{stateNote}</span> : null}
      {footnote ? <span className="field-help">{footnote}</span> : null}
      {shown?.frozen ? <span className="field-help">{t("todoFines.todo.frozenHint")}</span> : null}
      {amountInvalid ? <span className="field-help todo-fine-error">{t("todoFines.todo.applyInvalid")}</span> : null}

      {!onDraftChange && changed ? (
        <div>
          <button type="button" className="button-secondary" disabled={saving || !settings} onClick={() => void apply()}>
            {t("todoFines.todo.apply")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
