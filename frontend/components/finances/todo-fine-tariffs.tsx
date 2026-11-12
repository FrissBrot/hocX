"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { ActionIcon } from "@/components/ui/action-icons";
import { Badge } from "@/components/ui/badge";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { participantInitials } from "@/lib/utils/avatar";
import type { FineTariffGroup, FineTariffMember } from "@/types/api";

type MemberFilter = "all" | "none" | string;

/**
 * Tarife (z. B. Lernende, Vollverdiener) und Tarif je Person (Design «hocX Pendenzen-Bussen Tarife»).
 * Ein Tarif gilt für Pendenzen-Bussen (Beträge je Regel) und für Anwesenheitsbussen (eigene
 * Beträge für Verspätung/Absenz, leer = Vereinstarif, Migration 0172). Nur mit finances.manage.
 */
export function TodoFineTariffs({ tariffs, setTariffs, canManage, onChanged }: {
  tariffs: FineTariffGroup[];
  setTariffs: (tariffs: FineTariffGroup[]) => void;
  canManage: boolean;
  onChanged: () => Promise<void>;
}) {
  const t = useTranslations("finances");
  const tCommon = useTranslations("common");
  const confirm = useConfirm();
  const showToast = useToast();
  const [members, setMembers] = useState<FineTariffMember[] | null>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<MemberFilter>("all");
  const [selected, setSelected] = useState<string[]>([]);
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
      setEditing(null);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("todoFines.saveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  async function remove(tariff: FineTariffGroup) {
    const ok = await confirm({ message: t("todoFines.tariffDeleteConfirm", { name: tariff.name, count: tariff.member_count }), tone: "danger", confirmLabel: tCommon("delete") });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/todo-fines/tariffs/${tariff.id}`, { method: "DELETE" });
      await reloadTariffs();
      setMembers((current) => current?.map((member) => member.tariff_group_id === tariff.id ? { ...member, tariff_group_id: null } : member) ?? null);
      if (filter === tariff.id) setFilter("all");
      await onChanged();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("todoFines.saveFailed"), "error");
    }
  }

  async function assign(participantIds: string[], tariffId: string | null) {
    try {
      const updated = await Promise.all(participantIds.map((id) =>
        browserApiFetch<FineTariffMember>(`/api/todo-fines/tariff-members/${id}`, { method: "PUT", body: JSON.stringify({ tariff_group_id: tariffId }) })
      ));
      const byId = new Map(updated.map((member) => [member.participant_id, member]));
      setMembers((current) => current?.map((item) => byId.get(item.participant_id) ?? item) ?? null);
      await reloadTariffs();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("todoFines.saveFailed"), "error");
    }
  }

  const allMembers = useMemo(() => members ?? [], [members]);
  const ownCount = (tariffId: string) => allMembers.filter((member) => member.tariff_group_id === tariffId).length;
  const withoutTariff = allMembers.filter((member) => !member.tariff_group_id).length;

  const visible = useMemo(() => {
    const query = search.trim().toLowerCase();
    return allMembers.filter((member) =>
      (!query || member.display_name.toLowerCase().includes(query))
      && (filter === "all" || (filter === "none" ? !member.tariff_group_id : member.tariff_group_id === filter)));
  }, [allMembers, search, filter]);
  const allChecked = visible.length > 0 && visible.every((member) => selected.includes(member.participant_id));

  function toggleAll() {
    setSelected((current) => allChecked
      ? current.filter((id) => !visible.some((member) => member.participant_id === id))
      : Array.from(new Set([...current, ...visible.map((member) => member.participant_id)])));
  }

  const chips: { id: MemberFilter; label: string; count: number }[] = [
    { id: "all", label: t("todoFines.membersAll"), count: allMembers.length },
    { id: "none", label: t("todoFines.membersWithoutTariff"), count: withoutTariff },
    ...tariffs.map((tariff) => ({ id: tariff.id, label: tariff.name, count: ownCount(tariff.id) })),
  ];
  const assignOptions: { id: string | null; label: string; title?: string }[] = [
    { id: null, label: defaultTariff ? t("todoFines.defaultTariff") : t("todoFines.noTariff"), title: defaultTariff ? t("todoFines.useDefault", { name: defaultTariff.name }) : undefined },
    ...tariffs.map((tariff) => ({ id: tariff.id, label: tariff.name })),
  ];
  const editingDefault = editing !== null && editing !== "new" && editing.is_default;

  return (
    <div className="grid fine-tariffs">
      <section className="fine-tariffs-section">
        <div className="fine-tariffs-head">
          <div>
            <h2 className="section-title">{t("todoFines.tariffsTitle")}</h2>
            <p className="muted">{t("todoFines.tariffsDescription")}</p>
          </div>
          {canManage ? <button type="button" className="button-primary" onClick={() => open("new")}>{t("todoFines.addTariff")}</button> : null}
        </div>
        {tariffs.length === 0 ? <p className="muted">{t("todoFines.noTariffs")}</p> : (
          <div className="fine-tariff-cards">
            {tariffs.map((tariff) => {
              const own = ownCount(tariff.id);
              const total = own + (tariff.is_default ? withoutTariff : 0);
              const attendance = [
                tariff.amount_late != null ? t("todoFines.cardLate", { amount: tariff.amount_late.toFixed(2) }) : null,
                tariff.amount_absent != null ? t("todoFines.cardAbsent", { amount: tariff.amount_absent.toFixed(2) }) : null,
              ].filter(Boolean).join(" · ");
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
                  <div className="fine-tariff-card-total">
                    <strong>{members === null ? "–" : total}</strong>
                    <span className="muted">{t("todoFines.peopleLabel", { count: total })}</span>
                  </div>
                  <span className="muted fine-tariff-card-detail">
                    {tariff.is_default
                      ? t("todoFines.cardDefaultDetail", { own, rest: withoutTariff })
                      : own ? t("todoFines.cardAllAssigned") : t("todoFines.cardNobody")}
                  </span>
                  <span className="muted fine-tariff-card-detail">{attendance || t("todoFines.cardClubTariff")}</span>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="fine-tariffs-section">
        <div>
          <h2 className="section-title">{t("todoFines.membersTitle")}</h2>
          <p className="muted">{defaultTariff ? t("todoFines.membersDescription", { name: defaultTariff.name }) : t("todoFines.membersNoDefault")}</p>
        </div>
        <div className="fine-members-toolbar">
          <div className="fine-members-search">
            <SearchInput value={search} onChange={setSearch} placeholder={t("todoFines.membersSearch")} />
          </div>
          <div className="fine-members-chips">
            {chips.map((chip) => (
              <button key={chip.id} type="button" className={`fine-members-chip${filter === chip.id ? " fine-members-chip-active" : ""}`} aria-pressed={filter === chip.id} onClick={() => setFilter(chip.id)}>
                {chip.label}<span>{chip.count}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="fine-members">
          {canManage && selected.length > 0 ? (
            <div className="fine-members-bulk">
              <strong>{t("todoFines.selectedCount", { count: selected.length })}</strong>
              <span>{t("todoFines.bulkSet")}</span>
              <div className="fine-members-bulk-options">
                {assignOptions.map((option) => (
                  <button key={option.id ?? "default"} type="button" onClick={() => { void assign(selected, option.id); setSelected([]); }}>{option.label}</button>
                ))}
              </div>
              <button type="button" className="fine-members-bulk-clear" onClick={() => setSelected([])}>{t("todoFines.bulkClear")}</button>
            </div>
          ) : null}
          <div className="fine-members-row fine-members-head">
            {canManage ? <input type="checkbox" checked={allChecked} onChange={toggleAll} aria-label={t("todoFines.selectAll")} /> : <span />}
            <span>{t("todoFines.colPerson")}</span>
            <span>{t("todoFines.colTariff")}</span>
          </div>
          {members === null ? <p className="muted fine-members-empty">{t("todoFines.loading")}</p> : null}
          {members !== null && visible.length === 0 ? <p className="muted fine-members-empty">{t("todoFines.noMembers")}</p> : null}
          {visible.map((member) => {
            const checked = selected.includes(member.participant_id);
            return (
              <div key={member.participant_id} className={`fine-members-row${checked ? " fine-members-row-selected" : ""}${member.is_active ? "" : " fine-members-row-inactive"}`}>
                {canManage ? (
                  <input type="checkbox" checked={checked} aria-label={t("todoFines.selectPerson", { name: member.display_name })}
                    onChange={() => setSelected((current) => checked ? current.filter((id) => id !== member.participant_id) : [...current, member.participant_id])} />
                ) : <span />}
                <div className="fine-members-person">
                  <span className="fine-members-avatar" aria-hidden="true">{participantInitials({ display_name: member.display_name })}</span>
                  <div>
                    <div className="fine-members-name">{member.display_name}</div>
                    {member.is_active ? null : <div className="muted fine-members-inactive">{t("todoFines.inactivePerson")}</div>}
                  </div>
                </div>
                <div className="fine-members-segment" role="radiogroup" aria-label={t("todoFines.colTariff")}>
                  {assignOptions.map((option) => (
                    <button key={option.id ?? "default"} type="button" role="radio" title={option.title}
                      aria-checked={member.tariff_group_id === option.id}
                      className={member.tariff_group_id === option.id ? "fine-members-segment-active" : ""}
                      disabled={!canManage}
                      onClick={() => member.tariff_group_id !== option.id && void assign([member.participant_id], option.id)}>
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
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
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("fineSettings.amountLate")}</span>
              <input type="number" min="0" step="0.50" inputMode="decimal" value={amountLate} placeholder={t("fineSettings.clubTariff")} onChange={(event) => setAmountLate(event.target.value)} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("fineSettings.amountAbsent")}</span>
              <input type="number" min="0" step="0.50" inputMode="decimal" value={amountAbsent} placeholder={t("fineSettings.clubTariff")} onChange={(event) => setAmountAbsent(event.target.value)} />
            </label>
          </div>
          <span className="field-help">{t("fineSettings.tariffAmountsHelp")}</span>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setEditing(null)}>{tCommon("cancel")}</button>
            <button data-modal-save type="submit" className="button-primary" disabled={!name.trim() || !amountsValid || saving}>{tCommon("save")}</button>
          </div>
        </ModalSaveForm>
      </Modal>
    </div>
  );
}
