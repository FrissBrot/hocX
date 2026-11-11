"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { Select } from "@/components/ui/select";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import type { FineTariffGroup, FineTariffMember } from "@/types/api";

/** Tarife (z. B. Lernende, Vollverdiener) und Tarif je Person. Nur mit finances.manage. */
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
  const [editing, setEditing] = useState<FineTariffGroup | "new" | null>(null);
  const [name, setName] = useState("");
  const [isDefault, setIsDefault] = useState(false);
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
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing || !name.trim()) return;
    setSaving(true);
    try {
      await browserApiFetch(editing === "new" ? "/api/todo-fines/tariffs" : `/api/todo-fines/tariffs/${editing.id}`, {
        method: editing === "new" ? "POST" : "PUT",
        body: JSON.stringify({ name: name.trim(), is_default: isDefault }),
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
      await onChanged();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("todoFines.saveFailed"), "error");
    }
  }

  async function assign(member: FineTariffMember, tariffId: string) {
    try {
      const updated = await browserApiFetch<FineTariffMember>(`/api/todo-fines/tariff-members/${member.participant_id}`, {
        method: "PUT",
        body: JSON.stringify({ tariff_group_id: tariffId || null }),
      });
      setMembers((current) => current?.map((item) => item.participant_id === updated.participant_id ? updated : item) ?? null);
      await reloadTariffs();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("todoFines.saveFailed"), "error");
    }
  }

  const visibleMembers = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (members ?? []).filter((member) => !query || member.display_name.toLowerCase().includes(query));
  }, [members, search]);

  return (
    <div className="grid">
      <div className="todo-fine-toolbar">
        <p className="muted">{t("todoFines.tariffsDescription")}</p>
        {canManage ? <button type="button" className="button-primary" onClick={() => open("new")}>{t("todoFines.addTariff")}</button> : null}
      </div>
      <DataTable columns={[t("todoFines.colTariff"), t("todoFines.colMembers"), ...(canManage ? [tCommon("actions")] : [])]} emptyMessage={t("todoFines.noTariffs")}>
        {tariffs.map((tariff) => (
          <tr key={tariff.id}>
            <td><strong>{tariff.name}</strong> {tariff.is_default ? <Badge variant="info">{t("todoFines.defaultTariff")}</Badge> : null}</td>
            <td>{tariff.member_count}</td>
            {canManage ? (
              <td>
                <div className="table-actions table-actions-start">
                  <button type="button" className="row-text-action" onClick={() => open(tariff)}>{tCommon("edit")}</button>
                  <button type="button" className="row-text-action row-text-action-danger" onClick={() => void remove(tariff)}>{tCommon("delete")}</button>
                </div>
              </td>
            ) : null}
          </tr>
        ))}
      </DataTable>

      <h2 className="section-title">{t("todoFines.membersTitle")}</h2>
      <p className="muted">{defaultTariff ? t("todoFines.membersDescription", { name: defaultTariff.name }) : t("todoFines.membersNoDefault")}</p>
      <div className="list-filter-row">
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder={t("todoFines.membersSearch")} />
        </div>
      </div>
      <DataTable columns={[t("todoFines.colPerson"), t("todoFines.colTariff")]} emptyMessage={members === null ? t("todoFines.loading") : t("todoFines.noMembers")}>
        {visibleMembers.map((member) => (
          <tr key={member.participant_id} className={member.is_active ? "" : "table-row-done"}>
            <td>{member.display_name}</td>
            <td>
              <Select value={member.tariff_group_id ?? ""} disabled={!canManage || tariffs.length === 0} aria-label={t("todoFines.colTariff")}
                onChange={(event) => void assign(member, event.target.value)}>
                <option value="">{defaultTariff ? t("todoFines.useDefault", { name: defaultTariff.name }) : t("todoFines.noTariff")}</option>
                {tariffs.map((tariff) => <option key={tariff.id} value={tariff.id}>{tariff.name}</option>)}
              </Select>
            </td>
          </tr>
        ))}
      </DataTable>

      <Modal open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? t("todoFines.addTariff") : t("todoFines.editTariff")}>
        <ModalSaveForm className="grid" onSubmit={submit}>
          <label className="field-stack">
            <span className="field-label">{t("todoFines.tariffName")}</span>
            <input value={name} maxLength={120} autoFocus onChange={(event) => setName(event.target.value)} />
            <span className="field-help">{t("todoFines.tariffNameHelp")}</span>
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={isDefault} disabled={editing !== "new" && editing?.is_default} onChange={(event) => setIsDefault(event.target.checked)} />
            <span>{t("todoFines.defaultTariffLabel")}</span>
          </label>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setEditing(null)}>{tCommon("cancel")}</button>
            <button data-modal-save type="submit" className="button-primary" disabled={!name.trim() || saving}>{tCommon("save")}</button>
          </div>
        </ModalSaveForm>
      </Modal>
    </div>
  );
}
