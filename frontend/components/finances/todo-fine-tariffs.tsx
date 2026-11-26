"use client";

import type { Route } from "next";
import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ActionIcon } from "@/components/ui/action-icons";
import { Badge } from "@/components/ui/badge";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { financeErrorMessage } from "@/components/finances/finance-errors";
import { formatMoney } from "@/lib/utils/format";
import type { FineTariff, FineTariffGroup, FineTariffMember } from "@/types/api";

/**
 * Tarife (z. B. Lernende, Vollverdiener). Wer welchen Tarif hat, steht seit dem Konzept «Personen
 * an einem Ort» bei den Mitgliedern (Personenseite, Mehrfachauswahl); die Karte verlinkt dorthin.
 * Ein Tarif gilt für Pendenzen-Bussen (Beträge je Regel) und für Anwesenheitsbussen (eigene
 * Beträge für Verspätung/Absenz, leer = Vereinstarif, Migration 0172). Nur mit finances.manage.
 */
export function TodoFineTariffs({ tariffs, setTariffs, canManage, clubTariff = null, currency = "", onChanged }: {
  tariffs: FineTariffGroup[];
  setTariffs: (tariffs: FineTariffGroup[]) => void;
  canManage: boolean;
  /** Bussentarif aus «Verspätung & Absenz» - Platzhalter der leeren Tarif-Beträge */
  clubTariff?: FineTariff | null;
  currency?: string;
  onChanged: () => Promise<void>;
}) {
  const t = useTranslations("finances");
  const locale = useLocale();
  const money = (amount: number | null | undefined) => formatMoney(amount, currency, locale, { currencyFirst: true });
  const tCommon = useTranslations("common");
  const confirm = useConfirm();
  const showToast = useToast();
  const [members, setMembers] = useState<FineTariffMember[] | null>(null);
  const [editing, setEditing] = useState<FineTariffGroup | "new" | null>(null);
  const [name, setName] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const [amountLate, setAmountLate] = useState("");
  const [amountAbsent, setAmountAbsent] = useState("");
  const [saving, setSaving] = useState(false);
  const defaultTariff = tariffs.find((tariff) => tariff.is_default) ?? null;

  useEffect(() => {
    let cancelled = false;
    browserApiFetch<FineTariffMember[]>("/api/todo-fines/tariff-members")
      .then((loaded) => { if (!cancelled) setMembers(loaded); })
      .catch((error) => { if (!cancelled) showToast(error instanceof Error ? error.message : t("todoFines.loadFailed"), "error"); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function reloadTariffs() {
    setTariffs(await browserApiFetch<FineTariffGroup[]>("/api/todo-fines/tariffs"));
  }

  function open(target: FineTariffGroup | "new") {
    setEditing(target);
    setName(target === "new" ? "" : target.name);
    setIsDefault(target === "new" ? tariffs.length === 0 : target.is_default);
    setAmountLate(target === "new" || target.amount_late == null ? "" : String(target.amount_late));
    setAmountAbsent(target === "new" || target.amount_absent == null ? "" : String(target.amount_absent));
  }

  // Leer = Vereinstarif (null), sonst ein Betrag >= 0
  const parseAmount = (value: string): number | null => (value.trim() === "" ? null : Number(value.replace(",", ".")));
  const amountsValid = [amountLate, amountAbsent].every((value) => {
    const parsed = parseAmount(value);
    return parsed === null || (Number.isFinite(parsed) && parsed >= 0);
  });

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing || !name.trim()) return;
    setSaving(true);
    try {
      await browserApiFetch(editing === "new" ? "/api/todo-fines/tariffs" : `/api/todo-fines/tariffs/${editing.id}`, {
        method: editing === "new" ? "POST" : "PUT",
        body: JSON.stringify({ name: name.trim(), is_default: isDefault, amount_late: parseAmount(amountLate), amount_absent: parseAmount(amountAbsent) }),
      });
      await reloadTariffs();
      showToast(editing === "new" ? t("todoFines.tariffCreated", { name: name.trim() }) : t("todoFines.tariffSavedToast"), "success");
      setEditing(null);
    } catch (error) {
      // Doppelter Name: übersetzte Meldung statt «Tariff name already exists» (Backend-Code)
      const code = (error as { detail?: { code?: unknown } } | null)?.detail?.code;
      showToast(code === "tariff_name_taken" ? t("todoFines.tariffNameTaken", { name: name.trim() }) : financeErrorMessage(error, t, "todoFines.saveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  async function remove(tariff: FineTariffGroup) {
    const ok = await confirm({
      title: t("todoFines.tariffDeleteTitle", { name: tariff.name }),
      message: t("todoFines.tariffDeleteRest", { count: tariff.member_count }),
      tone: "danger",
      confirmLabel: tCommon("delete"),
    });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/todo-fines/tariffs/${tariff.id}`, { method: "DELETE" });
      await reloadTariffs();
      setMembers((current) => current?.map((member) => member.tariff_group_id === tariff.id ? { ...member, tariff_group_id: null } : member) ?? null);
      showToast(t("todoFines.tariffDeleted", { name: tariff.name }), "success");
      await onChanged();
    } catch (error) {
      showToast(financeErrorMessage(error, t, "todoFines.saveFailed"), "error");
    }
  }

  const allMembers = useMemo(() => members ?? [], [members]);
  const ownCount = (tariffId: string) => allMembers.filter((member) => member.tariff_group_id === tariffId).length;
  const withoutTariff = allMembers.filter((member) => !member.tariff_group_id).length;

  const editingDefault = editing !== null && editing !== "new" && editing.is_default;

  return (
    <div className="grid fine-tariffs">
      <section className="fine-tariffs-section">
        <div className="fine-tariffs-head">
          <div>
            <h2 className="section-title">{t("todoFines.tariffsTitle")}</h2>
            <p className="muted">{t("todoFines.tariffsDescription")}</p>
          </div>
          {canManage ? (
            <button type="button" className="button-primary" onClick={() => open("new")}>
              <ActionIcon name="add" />
              {t("todoFines.addTariff")}
            </button>
          ) : null}
        </div>
        {tariffs.length === 0 ? (
          <div className="fine-tariffs-empty">
            <div>
              <strong>{t("todoFines.noTariffs")}</strong>
              <span className="muted">{t("todoFines.noTariffsHint")}</span>
            </div>
            {canManage ? <button type="button" className="button-secondary" onClick={() => open("new")}>{t("todoFines.firstTariff")}</button> : null}
          </div>
        ) : (
          <div className="fine-tariff-cards">
            {tariffs.map((tariff) => {
              const own = ownCount(tariff.id);
              const total = own + (tariff.is_default ? withoutTariff : 0);
              const amounts = [
                { key: "late", label: t("todoFines.chipLate", { amount: tariff.amount_late != null ? money(tariff.amount_late) : t("todoFines.chipStandard") }), own: tariff.amount_late != null },
                { key: "absent", label: t("todoFines.chipAbsent", { amount: tariff.amount_absent != null ? money(tariff.amount_absent) : t("todoFines.chipStandard") }), own: tariff.amount_absent != null },
              ];
              return (
                <div key={tariff.id} className={`fine-tariff-card${tariff.is_default ? " fine-tariff-card-default" : ""}`}>
                  <div className="fine-tariff-card-head">
                    <strong>{tariff.name}</strong>
                    {tariff.is_default ? <Badge variant="info">{t("todoFines.defaultTariff")}</Badge> : null}
                    {canManage ? (
                      <span className="fine-tariff-card-actions">
                        <button type="button" className="button-icon-soft button-icon-soft-sm" aria-label={tCommon("edit")} onClick={() => open(tariff)}><ActionIcon name="edit" /></button>
                        <button type="button" className="button-icon-soft button-icon-soft-sm button-icon-soft-danger" aria-label={tCommon("delete")} onClick={() => void remove(tariff)}><ActionIcon name="delete" /></button>
                      </span>
                    ) : null}
                  </div>
                  <Link className="fine-tariff-card-total" href={`/participants?tariff=${tariff.id}` as Route}>
                    <strong>{members === null ? "–" : total}</strong>
                    <span className="muted">{t("todoFines.peopleLabel", { count: total })} →</span>
                  </Link>
                  <span className="muted fine-tariff-card-detail">
                    {tariff.is_default
                      ? t("todoFines.cardDefaultDetail", { own, rest: withoutTariff })
                      : own ? t("todoFines.cardAllAssigned") : t("todoFines.cardNobody")}
                  </span>
                  <div className="fine-tariff-card-amounts">
                    {amounts.map((amount) => (
                      <span key={amount.key} className={amount.own ? "fine-tariff-chip" : "fine-tariff-chip fine-tariff-chip-standard"}>{amount.label}</span>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>


      <Modal open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? t("todoFines.addTariff") : t("todoFines.editTariff")}>
        <ModalSaveForm className="grid" onSubmit={submit}>
          <label className="field-stack">
            <span className="field-label">{t("todoFines.tariffName")}</span>
            <input value={name} maxLength={120} autoFocus placeholder={t("todoFines.tariffNamePlaceholder")} onChange={(event) => setName(event.target.value)} />
            <span className="field-help">{t("todoFines.tariffNameHelp")}</span>
          </label>
          <label className={`fine-rule-active fine-tariff-default${editingDefault ? " fine-tariff-default-locked" : ""}`}>
            <input type="checkbox" role="switch" checked={isDefault} disabled={editingDefault} onChange={(event) => setIsDefault(event.target.checked)} />
            <span className="album-picker-switch-track" aria-hidden="true" />
            <span className="fine-rule-active-text">
              <strong>{t("todoFines.defaultTariffLabel")}</strong>
              <span className="field-help">
                {editingDefault
                  ? t("todoFines.defaultLockedHint")
                  : defaultTariff && isDefault && editing !== null && (editing === "new" || editing.id !== defaultTariff.id)
                    ? t("todoFines.defaultReplaceHint", { name: defaultTariff.name })
                    : t("todoFines.defaultHint")}
              </span>
            </span>
          </label>
          <div className="field-stack">
            <span className="field-label">{t("fineSettings.attendanceGroup")}</span>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-help">{t("fineSettings.amountLate")}</span>
                <span className="fine-amount-input">
                  {currency ? <span className="fine-amount-currency" aria-hidden="true">{currency}</span> : null}
                  <input type="number" min="0" step="0.50" inputMode="decimal" value={amountLate}
                    placeholder={clubTariff ? t("todoFines.standardPlaceholder", { amount: money(clubTariff.amount_late) }) : t("fineSettings.clubTariff")}
                    onChange={(event) => setAmountLate(event.target.value)} />
                </span>
              </label>
              <label className="field-stack">
                <span className="field-help">{t("fineSettings.amountAbsent")}</span>
                <span className="fine-amount-input">
                  {currency ? <span className="fine-amount-currency" aria-hidden="true">{currency}</span> : null}
                  <input type="number" min="0" step="0.50" inputMode="decimal" value={amountAbsent}
                    placeholder={clubTariff ? t("todoFines.standardPlaceholder", { amount: money(clubTariff.amount_absent) }) : t("fineSettings.clubTariff")}
                    onChange={(event) => setAmountAbsent(event.target.value)} />
                </span>
              </label>
            </div>
            <span className="field-help">{t("fineSettings.tariffAmountsHelp")}</span>
          </div>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setEditing(null)}>{tCommon("cancel")}</button>
            <button data-modal-save type="submit" className="button-primary" disabled={!name.trim() || !amountsValid || saving}>{tCommon("save")}</button>
          </div>
        </ModalSaveForm>
      </Modal>
    </div>
  );
}
