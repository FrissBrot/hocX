"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { ActionIcon } from "@/components/ui/action-icons";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { DataTable } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { Select } from "@/components/ui/select";
import { useOpenRequest } from "@/lib/search/handoff";
import { browserApiFetch, LONG_RUNNING_TIMEOUT_MS } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { formatDate } from "@/lib/utils/format";
import { roleName } from "@/lib/permissions";
import type { FineTariffGroup, ParticipantBulkResult, ParticipantSummary, RoleRead, RoleRef, TemplateSummary } from "@/types/api";
import { avatarTone, participantInitials } from "@/lib/utils/avatar";
import { CSV_TEMPLATE, CsvPreview, parseParticipantCsv } from "@/lib/utils/participant-csv";
import { apiErrorMessage } from "@/lib/api/error-message";
import { HelpPopover } from "@/components/ui/help-popover";
import { StatusBanner } from "@/components/ui/status-banner";
import { defaultRoleIds } from "@/components/users/user-form-shared";

// Alle Personen auf einmal laden (wie die Auswahllisten, Obergrenze der Route 2000): Suche, Tabs
// und Zähler arbeiten sonst nur über die ersten Seiten (Bereichs-Audit 05). Darüber lädt
// «Mehr laden» weiter.
const PAGE_SIZE = 2000;

type ImportResult = { imported: ParticipantSummary[]; duplicates: string[]; errors: string[] };

function downloadCsvTemplate() {
  const url = URL.createObjectURL(new Blob([CSV_TEMPLATE], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "hocx-mitglieder-vorlage.csv"; // i18n-ok: Dateiname
  link.click();
  URL.revokeObjectURL(url);
}

export type MemberListPermissions = {
  // Login/Rollen ändern, einladen (access.manage)
  access: boolean;
  // Tarif sehen (finances.read) bzw. ändern (finances.manage)
  financeRead: boolean;
  financeManage: boolean;
};

type ParticipantManagerProps = {
  initialParticipants: ParticipantSummary[];
  templates: TemplateSummary[];
  tenantId: string | null;
  // Rollen des Mandanten (nur mit access.manage geladen, sonst leer)
  roles: RoleRead[];
  tariffs: FineTariffGroup[];
  permissions: MemberListPermissions;
  // Vorbelegung des Tarif-Filters (/participants?tariff=<id>, Links aus den Bussen-Regeln)
  initialTariffFilter?: string | null;
};

type NewMemberForm = {
  first_name: string;
  last_name: string;
  display_name: string;
  email: string;
  joined_at: string;
  template_ids: string[];
  tariff_id: string;
  invite: boolean;
  role_id: string;
};

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

type StatusFilter = "all" | "active" | "inactive" | "left";
type LoginFilter = "all" | "active" | "invited" | "none";
type MembershipTone = "success" | "warning" | "info" | "neutral";
type BulkModal = "invite" | "tariff" | "roles" | null;

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Filter-Kategorie für die Tabs: "Ausgetreten" (Austrittsdatum vorbei) hat Vorrang vor dem
 * manuellen is_active-Schalter, damit sich die drei Tabs zu "Alle" aufsummieren. */
function participantCategory(participant: ParticipantSummary, today: string): Exclude<StatusFilter, "all"> {
  // left_at ist inklusiv - am Austrittstag selbst ist die Person noch Mitglied
  // (siehe participant_eligible_on und den Hilfetext "Erscheint ab dem Folgetag nicht
  // mehr in Anwesenheitslisten").
  if (participant.left_at && participant.left_at < today) return "left";
  return participant.is_active ? "active" : "inactive";
}

/** Mitgliedschafts-Zeile ("Ausgetreten seit …" / "Eintritt ab …" / "Mitglied seit JJJJ") aus
 * joined_at/left_at. Unabhängig vom is_active-Schalter: die Daten steuern, in welchen
 * Anwesenheitslisten jemand erscheint. Reine Hilfsfunktion, daher `t` als Parameter. */
function membershipInfo(participant: ParticipantSummary, today: string, t: TFunc): { label: string; tone: MembershipTone } {
  if (participant.left_at && participant.left_at < today) {
    return { label: t("membership.leftSince", { date: formatDate(participant.left_at) }), tone: "warning" };
  }
  if (participant.joined_at && participant.joined_at > today) {
    return { label: t("membership.joinsFrom", { date: formatDate(participant.joined_at) }), tone: "info" };
  }
  if (participant.left_at) {
    return { label: t("membership.leavesOn", { date: formatDate(participant.left_at) }), tone: "warning" };
  }
  if (participant.joined_at) {
    return { label: t("membership.memberSince", { year: participant.joined_at.slice(0, 4) }), tone: "success" };
  }
  return { label: t("membership.noJoinDate"), tone: "neutral" };
}

const loginStatusOf = (participant: ParticipantSummary): Exclude<LoginFilter, "all"> =>
  participant.login_status ?? (participant.login_enabled ? "active" : "none");

function emptyNewMember(roles: RoleRead[]): NewMemberForm {
  return {
    first_name: "", last_name: "", display_name: "", email: "", joined_at: todayIso(), template_ids: [], tariff_id: "",
    invite: false, role_id: defaultRoleIds(roles)[0] ?? roles[0]?.id ?? "",
  };
}

/** Mitgliederliste (Konzept «Personen an einem Ort»): einziger Ort zum Anlegen, Spalten Login,
 * Rollen und Tarif, Filter und Mehrfachaktionen. Ein Klick öffnet die Personenseite. */
export function ParticipantManager({ initialParticipants, templates, tenantId, roles, tariffs, permissions, initialTariffFilter = null }: ParticipantManagerProps) {
  const t = useTranslations("participants");
  const tNav = useTranslations("nav");
  const tSecurity = useTranslations("security");
  const router = useRouter();
  const showToast = useToast();
  const confirm = useConfirm();
  const [participants, setParticipants] = useState(initialParticipants);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");
  const [loginFilter, setLoginFilter] = useState<LoginFilter>("all");
  const [roleFilter, setRoleFilter] = useState("all");
  const [tariffFilter, setTariffFilter] = useState(() =>
    initialTariffFilter && tariffs.some((tariff) => tariff.id === initialTariffFilter) ? initialTariffFilter : "all");
  const [inviteAvailable, setInviteAvailable] = useState(false);
  const csvInputRef = useRef<HTMLInputElement>(null);
  const [newMember, setNewMember] = useState<NewMemberForm | null>(null);
  const [creating, setCreating] = useState(false);
  const [selectedParticipantIds, setSelectedParticipantIds] = useState<string[]>([]);
  const [bulkModal, setBulkModal] = useState<BulkModal>(null);
  const [bulkTariff, setBulkTariff] = useState("");
  const [bulkRoleId, setBulkRoleId] = useState("");
  const [bulkRolesMode, setBulkRolesMode] = useState<"add" | "remove">("add");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [csvPreview, setCsvPreview] = useState<(CsvPreview & { file: File }) | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [importing, setImporting] = useState(false);

  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [hasMore, setHasMore] = useState(initialParticipants.length === PAGE_SIZE);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  async function loadMore() {
    setIsLoadingMore(true);
    try {
      const next = await browserApiFetch<ParticipantSummary[]>(`/api/participants?include_former=true&skip=${participants.length}&limit=${PAGE_SIZE}`);
      setParticipants((current) => [...current, ...(next ?? [])]);
      setHasMore((next ?? []).length === PAGE_SIZE);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.loadMoreFailed"), "error");
    } finally {
      setIsLoadingMore(false);
    }
  }

  async function reloadAll() {
    const next = await browserApiFetch<ParticipantSummary[]>(`/api/participants?include_former=true&limit=${PAGE_SIZE}`);
    setParticipants(next ?? []);
    setHasMore((next ?? []).length === PAGE_SIZE);
  }

  const loadMoreSentinelRef = useInfiniteScroll({
    hasMore,
    isLoading: isLoadingMore,
    onLoadMore: () => void loadMore(),
  });

  useEffect(() => {
    if (!permissions.access) return;
    let cancelled = false;
    browserApiFetch<{ enabled: boolean }>("/api/auth/password-reset/available")
      .then((result) => { if (!cancelled) setInviteAvailable(Boolean(result?.enabled)); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [permissions.access]);

  // Treffer aus der globalen Suche (?open=<id>): Personenseite öffnen
  useOpenRequest(participants, (participant) => router.push(`/participants/${participant.id}`));

  const today = todayIso();
  const tariffName = useMemo(() => new Map(tariffs.map((tariff) => [tariff.id, tariff.name])), [tariffs]);
  const defaultTariff = tariffs.find((tariff) => tariff.is_default);
  const defaultTariffName = defaultTariff?.name ?? "";
  // Rollen für Filter/Anzeige: mit access.manage die Rollen des Mandanten, sonst die an Personen gefundenen
  const roleOptions = useMemo<RoleRef[]>(() => {
    if (roles.length) return roles;
    const seen = new Map<string, RoleRef>();
    for (const participant of participants) for (const role of participant.roles ?? []) seen.set(role.id, role);
    return [...seen.values()];
  }, [roles, participants]);

  const matchesSecondary = (participant: ParticipantSummary) =>
    (loginFilter === "all" || loginStatusOf(participant) === loginFilter)
    && (roleFilter === "all" || (participant.roles ?? []).some((role) => role.id === roleFilter))
    // Standardtarif: alle mit diesem Tarif und alle ohne eigenen Tarif (wie die Tarifkarte zählt)
    && (tariffFilter === "all" || (participant.tariff_id ?? "") === tariffFilter
      || (!participant.tariff_id && (tariffFilter === "" || tariffFilter === defaultTariff?.id)));

  const statusCounts = useMemo(() => {
    const group = participants.filter(matchesSecondary);
    const counts = { all: group.length, active: 0, inactive: 0, left: 0 };
    for (const participant of group) counts[participantCategory(participant, today)] += 1;
    return counts;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [participants, today, loginFilter, roleFilter, tariffFilter]);

  const filteredParticipants = useMemo(() => {
    const dir = sortDirection === "asc" ? 1 : -1;
    const query = search.trim().toLowerCase();
    return participants
      .filter(matchesSecondary)
      .filter((participant) => statusFilter === "all" || participantCategory(participant, today) === statusFilter)
      .filter((participant) => {
        const haystack = `${participant.display_name} ${participant.first_name ?? ""} ${participant.last_name ?? ""} ${participant.email ?? ""}`.toLowerCase();
        return !query || haystack.includes(query);
      })
      .sort((a, b) => a.display_name.toLowerCase().localeCompare(b.display_name.toLowerCase()) * dir);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [participants, search, statusFilter, sortDirection, today, loginFilter, roleFilter, tariffFilter]);

  const visibleIds = useMemo(() => filteredParticipants.map((participant) => participant.id), [filteredParticipants]);
  // Set statt Array.includes: bei grossen Listen sonst quadratisch pro Render.
  const selectedIdSet = useMemo(() => new Set(selectedParticipantIds), [selectedParticipantIds]);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIdSet.has(id));
  const someVisibleSelected = !allVisibleSelected && visibleIds.some((id) => selectedIdSet.has(id));

  function toggleSelectAllVisible(checked: boolean) {
    const visibleIdSet = new Set(visibleIds);
    setSelectedParticipantIds((current) =>
      checked ? [...new Set([...current, ...visibleIds])] : current.filter((id) => !visibleIdSet.has(id))
    );
  }

  const errorText = (error: unknown, fallback: string) => apiErrorMessage(error, tSecurity, "apiErrors", fallback);

  async function createMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newMember || !newMember.display_name.trim() || creating) return;
    setCreating(true);
    try {
      const created = await browserApiFetch<ParticipantSummary>("/api/participants", {
        method: "POST",
        body: JSON.stringify({
          tenant_id: tenantId,
          first_name: newMember.first_name.trim() || null,
          last_name: newMember.last_name.trim() || null,
          display_name: newMember.display_name.trim(),
          email: newMember.email.trim() || null,
          is_active: true,
          joined_at: newMember.joined_at || null,
          left_at: null,
        }),
      });
      if (newMember.template_ids.length) {
        await browserApiFetch(`/api/participants/${created.id}/templates`, { method: "PUT", body: JSON.stringify({ template_ids: newMember.template_ids }) });
      }
      if (permissions.financeManage && newMember.tariff_id) {
        await browserApiFetch(`/api/todo-fines/tariff-members/${created.id}`, { method: "PUT", body: JSON.stringify({ tariff_group_id: newMember.tariff_id }) });
      }
      if (permissions.access && newMember.invite && created.email) {
        if (newMember.role_id) {
          await browserApiFetch(`/api/participants/${created.id}`, { method: "PATCH", body: JSON.stringify({ role_ids: [newMember.role_id] }) });
        }
        await browserApiFetch(`/api/participants/${created.id}/invite`, { method: "POST" });
      }
      const fresh = await browserApiFetch<ParticipantSummary>(`/api/participants/${created.id}`);
      setParticipants((current) => [fresh, ...current]);
      setNewMember(null);
      showToast(newMember.invite ? t("newMember.createdInvited", { name: fresh.display_name }) : t("toasts.created", { name: fresh.display_name }), "success");
    } catch (error) {
      showToast(errorText(error, t("toasts.saveFailed")), "error");
    } finally {
      setCreating(false);
    }
  }

  function bulkSummary(result: ParticipantBulkResult, doneKey: string) {
    const names = new Map(participants.map((participant) => [participant.id, participant.display_name]));
    if (result.skipped.length) {
      const reasons = result.skipped.map((item) => `${names.get(item.participant_id) ?? "?"} (${t(`bulk.reasons.${item.reason}`)})`).join(", ");
      showToast(t("bulk.partial", { done: result.done.length, skipped: result.skipped.length, reasons }), result.done.length ? "info" : "error");
    } else {
      showToast(t(doneKey, { count: result.done.length }), "success");
    }
  }

  async function runBulk(action: () => Promise<void>) {
    setBulkBusy(true);
    try {
      await action();
      setBulkModal(null);
      await reloadAll();
    } catch (error) {
      showToast(errorText(error, t("bulk.failed")), "error");
    } finally {
      setBulkBusy(false);
    }
  }

  const bulkInvite = () => runBulk(async () => {
    const result = await browserApiFetch<ParticipantBulkResult>("/api/participants/bulk-invite", {
      method: "POST",
      body: JSON.stringify({ participant_ids: selectedParticipantIds, role_id: bulkRoleId || null }),
    });
    bulkSummary(result, "bulk.invited");
  });

  const bulkSetTariff = () => runBulk(async () => {
    await browserApiFetch("/api/todo-fines/tariff-members", {
      method: "PUT",
      body: JSON.stringify({ participant_ids: selectedParticipantIds, tariff_group_id: bulkTariff || null }),
    });
    showToast(t("bulk.tariffSet", { count: selectedParticipantIds.length }), "success");
  });

  const bulkRoles = () => runBulk(async () => {
    const result = await browserApiFetch<ParticipantBulkResult>("/api/participants/bulk-roles", {
      method: "POST",
      body: JSON.stringify({ participant_ids: selectedParticipantIds, role_ids: [bulkRoleId], mode: bulkRolesMode }),
    });
    bulkSummary(result, bulkRolesMode === "add" ? "bulk.rolesAdded" : "bulk.rolesRemoved");
  });

  function openBulk(kind: Exclude<BulkModal, null>) {
    setBulkTariff("");
    setBulkRolesMode("add");
    setBulkRoleId(kind === "invite" ? (defaultRoleIds(roles)[0] ?? "") : (roles[0]?.id ?? ""));
    setBulkModal(kind);
  }

  async function bulkDeleteParticipants() {
    if (!selectedParticipantIds.length) {
      return;
    }
    const ok = await confirm({
      title: t("deleteDialog.bulkTitle", { count: selectedParticipantIds.length }),
      message: t("deleteDialog.bulkMessage"),
      tone: "danger",
      confirmLabel: t("deleteDialog.confirm")
    });
    if (!ok) return;
    try {
      await browserApiFetch("/api/participants", {
        method: "DELETE",
        body: JSON.stringify({ participant_ids: selectedParticipantIds }),
      });
      const deletedIds = new Set(selectedParticipantIds);
      setParticipants((current) => current.filter((participant) => !deletedIds.has(participant.id)));
      setSelectedParticipantIds([]);
      showToast(t("toasts.bulkDeleted"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.bulkDeleteFailed"), "error");
    }
  }

  async function handleCsvFileSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const text = await file.text();
    setCsvPreview({ ...parseParticipantCsv(text), file });
  }

  async function confirmCsvImport() {
    if (!csvPreview) return;
    setImporting(true);
    try {
      const body = new FormData();
      body.append("file", csvPreview.file);
      const result = await browserApiFetch<ImportResult>("/api/participants/import-csv", {
        method: "POST",
        body,
        timeoutMs: LONG_RUNNING_TIMEOUT_MS,
      });
      setCsvPreview(null);
      setImportResult(result);
      await reloadAll();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.csvImportFailed"), "error");
      // Keeps the preview open on failure (audit F9, 2026-08-16) - a transient error
      // (network blip, brief server hiccup) shouldn't force re-selecting the file just to
      // retry the same import.
    } finally {
      setImporting(false);
    }
  }

  const hasNoParticipants = participants.length === 0 && !hasMore;
  const openCreate = () => setNewMember(emptyNewMember(roles));
  const selectionCount = selectedParticipantIds.length;

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("pageTitle")}</h1>
          <p className="muted">{hasNoParticipants ? t("pageDescriptionEmpty") : t("list.description")}</p>
        </div>
        {hasNoParticipants ? null : (
        <div className="table-toolbar-actions">
          <button type="button" className="button-secondary participant-header-button" onClick={() => csvInputRef.current?.click()}>
            <ActionIcon name="upload" />
            {t("csvImport")}
          </button>
          <button type="button" className="button-primary participant-header-button" onClick={openCreate}>
            <ActionIcon name="add" />
            {t("newParticipant")}
          </button>
        </div>
        )}
        <input ref={csvInputRef} type="file" accept=".csv,text/csv" onChange={(e) => void handleCsvFileSelected(e)} hidden />
      </div>

      {hasNoParticipants ? (
        <EmptyState
          title={t("emptyState.title")}
          description={t("emptyState.description")}
          actions={
            <>
              <button type="button" className="button-primary" onClick={openCreate}>
                {t("emptyState.addParticipant")}
              </button>
              <button type="button" className="button-secondary participant-header-button" onClick={() => csvInputRef.current?.click()}>
                {t("emptyState.importList")}
              </button>
            </>
          }
        />
      ) : (
      <>
      <div className="list-filter-row">
        <FilterTabs<StatusFilter>
          value={statusFilter}
          onChange={setStatusFilter}
          options={[
            { value: "active", label: t("filters.active"), count: statusCounts.active },
            { value: "all", label: t("filters.all"), count: statusCounts.all },
            { value: "inactive", label: t("filters.inactive"), count: statusCounts.inactive },
            { value: "left", label: t("filters.left"), count: statusCounts.left },
          ]}
        />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder={t("searchPlaceholder")} />
        </div>
      </div>
      <div className="participant-filter-selects">
        <label className="field-stack">
          <span className="field-label">{t("list.filterLogin")}</span>
          <Select value={loginFilter} onChange={(event) => setLoginFilter(event.target.value as LoginFilter)}>
            <option value="all">{t("list.any")}</option>
            <option value="active">{t("person.loginStatus.active")}</option>
            <option value="invited">{t("person.loginStatus.invited")}</option>
            <option value="none">{t("person.loginStatus.none")}</option>
          </Select>
        </label>
        <label className="field-stack">
          <span className="field-label">{t("list.filterRole")}</span>
          <Select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
            <option value="all">{t("list.any")}</option>
            {roleOptions.map((role) => <option key={role.id} value={role.id}>{roleName(role, tNav)}</option>)}
          </Select>
        </label>
        {permissions.financeRead ? (
          <label className="field-stack">
            <span className="field-label">{t("list.filterTariff")}</span>
            <Select value={tariffFilter} onChange={(event) => setTariffFilter(event.target.value)}>
              <option value="all">{t("list.any")}</option>
              {defaultTariff ? null : <option value="">{t("list.tariffDefault")}</option>}
              {tariffs.map((tariff) => (
                <option key={tariff.id} value={tariff.id}>{tariff.is_default ? t("person.tariffStandard", { name: tariff.name }) : tariff.name}</option>
              ))}
            </Select>
          </label>
        ) : null}
      </div>

      {selectionCount > 0 ? (
        <div className="participant-bulk-bar" role="region" aria-label={t("bulk.label")}>
          <strong>{t("bulk.selected", { count: selectionCount })}</strong>
          {permissions.financeManage ? <button type="button" className="button-secondary" onClick={() => openBulk("tariff")}>{t("bulk.setTariff")}</button> : null}
          {permissions.access ? <button type="button" className="button-secondary" onClick={() => openBulk("invite")} disabled={!inviteAvailable}>{t("bulk.invite")}</button> : null}
          {permissions.access ? <button type="button" className="button-secondary" onClick={() => openBulk("roles")}>{t("bulk.roles")}</button> : null}
          <button type="button" className="button-secondary button-danger" onClick={() => void bulkDeleteParticipants()}>{t("bulk.delete")}</button>
          <button type="button" className="button-ghost" onClick={() => setSelectedParticipantIds([])}>{t("bulk.clear")}</button>
        </div>
      ) : null}

      <DataTable
        className="data-table-lg participant-table"
        columns={[
          {
            key: "select",
            label: t("selectAll"),
            header: (
              <input
                type="checkbox"
                aria-label={t("selectAll")}
                checked={allVisibleSelected}
                ref={(element) => {
                  if (element) element.indeterminate = someVisibleSelected;
                }}
                onChange={(event) => toggleSelectAllVisible(event.target.checked)}
              />
            ),
          },
          { key: "display_name", label: t("columns.name"), sortable: true, sortDirection, onSort: () => setSortDirection((d) => (d === "asc" ? "desc" : "asc")) },
          { key: "membership", label: t("columns.membership") },
          { key: "login", label: t("list.columns.login") },
          { key: "roles", label: t("list.columns.roles") },
          ...(permissions.financeRead ? [{ key: "tariff", label: t("list.columns.tariff") }] : []),
        ]}
        emptyMessage={t("emptyFiltered")}
        footer={
          <>
            <span>{t("footerCount", { count: filteredParticipants.length })}</span>
            <span>{t("list.footerHint")}</span>
          </>
        }
      >
        {filteredParticipants.map((participant) => {
          const isSelected = selectedIdSet.has(participant.id);
          const membership = membershipInfo(participant, today, t);
          const login = loginStatusOf(participant);
          return (
            <tr
              key={participant.id}
              className={`table-row-clickable${participant.is_active ? "" : " participant-row-inactive"}`}
              onClick={() => router.push(`/participants/${participant.id}`)}>
              <td onClick={(event) => event.stopPropagation()}>
                <input
                  type="checkbox"
                  aria-label={t("selectParticipant", { name: participant.display_name })}
                  checked={isSelected}
                  onChange={(event) =>
                    setSelectedParticipantIds((current) =>
                      event.target.checked ? [...current, participant.id] : current.filter((id) => id !== participant.id)
                    )
                  }
                />
              </td>
              <td>
                <div className="participant-name-cell">
                  <span className={`participant-avatar participant-avatar-tone-${avatarTone(participant.id)}`} aria-hidden="true">
                    {participantInitials(participant)}
                  </span>
                  <div className="participant-name-text">
                    <strong>{participant.display_name}</strong>
                    <span className="participant-name-sub">{participant.email ?? t("noEmail")}</span>
                  </div>
                </div>
              </td>
              <td>
                <span className={`participant-membership participant-membership-${membership.tone}`}>
                  <span className="participant-membership-dot" aria-hidden="true" />
                  {membership.label}
                </span>
                {participant.is_active ? null : <> <Badge variant="neutral">{t("statusInactive")}</Badge></>}
              </td>
              <td>
                {login === "none" ? <span className="muted">–</span> : (
                  <Badge variant={login === "active" ? "success" : "info"}>{t(`person.loginStatus.${login}`)}</Badge>
                )}
                {/* Ausgetretene können sich nicht mehr anmelden (Backend: AppUser.has_left) */}
                {login === "active" && participantCategory(participant, today) === "left" ? <Badge variant="warning">{t("membership.loginBlocked")}</Badge> : null}
              </td>
              <td>
                <span className="access-role-chips">
                  {login === "none" ? <span className="muted">–</span> : (participant.roles ?? []).map((role) => <Badge key={role.id} variant="neutral">{roleName(role, tNav)}</Badge>)}
                </span>
              </td>
              {permissions.financeRead ? (
                <td>{participant.tariff_id ? tariffName.get(participant.tariff_id) ?? "–" : <span className="muted">{t("list.tariffDefault")}</span>}</td>
              ) : null}
            </tr>
          );
        })}
      </DataTable>
      </>
      )}

      {hasMore && (
        <div className="load-more-row" ref={loadMoreSentinelRef}>
          {isLoadingMore ? (
            <span className="muted">{t("loadingMore")}</span>
          ) : (
            <button type="button" className="button-secondary button-ghost" onClick={() => void loadMore()}>
              {t("loadMore", { count: participants.length })}
            </button>
          )}
        </div>
      )}

      {/* CSV preview modal */}
      <Modal
        open={csvPreview !== null}
        onClose={() => setCsvPreview(null)}
        title={t("csvPreview.title")}
        description={t("csvPreview.description", { count: csvPreview?.rows.length ?? 0 })}
      >
        <div className="grid">
          <p className="field-help">
            {t("csvPreview.columns")}{" "}
            <HelpPopover topic={t("csvImport")} docs={{ page: "mitglieder", anchor: "import" }}>{t("csvPreview.help")}</HelpPopover>
          </p>
          {csvPreview && csvPreview.rows.length === 0 ? <StatusBanner tone="error" message={t("csvPreview.noRows")} /> : null}
          {csvPreview?.rows.length && csvPreview.missingEmailColumn ? <StatusBanner tone="neutral" message={t("csvPreview.noEmailColumn")} /> : null}
          <DataTable emptyMessage={t("csvPreview.empty")} columns={[t("csvPreview.displayName"), t("columns.firstName"), t("columns.lastName"), t("columns.email")]}>
            {(csvPreview?.rows ?? []).map((row, i) => (
              <tr key={i}>
                <td><strong>{row.display_name}</strong></td>
                <td>{row.first_name ?? <span className="muted">—</span>}</td>
                <td>{row.last_name ?? <span className="muted">—</span>}</td>
                <td>{row.email ?? <span className="muted">—</span>}</td>
              </tr>
            ))}
          </DataTable>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setCsvPreview(null)}>{t("csvPreview.cancel")}</button>
            <button type="button" className="button-secondary" onClick={downloadCsvTemplate}>{t("csvPreview.template")}</button>
            <button type="button" className="button-primary" onClick={() => void confirmCsvImport()} disabled={importing || !csvPreview?.rows.length}>
              {importing ? t("csvPreview.importing") : t("csvPreview.importEntries", { count: csvPreview?.rows.length ?? 0 })}
            </button>
          </div>
        </div>
      </Modal>

      {/* Import result modal */}
      <Modal
        open={importResult !== null}
        onClose={() => setImportResult(null)}
        title={t("importResult.title")}
        description=""
      >
        {importResult && (
          <div className="grid">
            <div className="status-row">
              <Badge variant="success">{t("importResult.imported", { count: importResult.imported.length })}</Badge>
              {importResult.duplicates.length > 0 && (
                <Badge variant="warning">{t("importResult.duplicatesSkipped", { count: importResult.duplicates.length })}</Badge>
              )}
              {importResult.errors.length > 0 && <Badge variant="danger">{t("importResult.errorsCount", { count: importResult.errors.length })}</Badge>}
            </div>
            {importResult.duplicates.length > 0 && (
              <div>
                <div className="field-label">{t("importResult.skippedExisting")}</div>
                <div className="muted" style={{ fontSize: "var(--text-base)", lineHeight: 1.7 }}>
                  {importResult.duplicates.join(", ")}
                </div>
              </div>
            )}
            {importResult.errors.length > 0 && (
              <div>
                <div className="field-label">{t("importResult.errorsLabel")}</div>
                <div className="muted" style={{ fontSize: "var(--text-base)", lineHeight: 1.7 }}>
                  {importResult.errors.map((row, i) => <div key={i}>{/^\d+$/.test(row) ? t("importResult.errorRow", { row }) : row}</div>)}
                </div>
              </div>
            )}
            <div className="table-toolbar-actions">
              <button type="button" className="button-secondary" onClick={() => setImportResult(null)}>{t("importResult.close")}</button>
            </div>
          </div>
        )}
      </Modal>

      {/* Neues Mitglied: einziger Ort zum Anlegen, optional gleich einladen (mit Rolle) und Tarif */}
      <Modal open={newMember !== null} onClose={() => setNewMember(null)} title={t("editModal.createTitle")} description={t("newMember.description")}>
        {newMember ? (
          <ModalSaveForm className="grid" onSubmit={createMember}>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">{t("editModal.firstName")}</span>
                <input value={newMember.first_name} onChange={(event) => setNewMember({ ...newMember, first_name: event.target.value })} />
              </label>
              <label className="field-stack">
                <span className="field-label">{t("editModal.lastName")}</span>
                <input value={newMember.last_name} onChange={(event) => setNewMember({ ...newMember, last_name: event.target.value })} />
              </label>
            </div>
            <label className="field-stack">
              <span className="field-label">{t("editModal.displayName")}</span>
              <input value={newMember.display_name} onChange={(event) => setNewMember({ ...newMember, display_name: event.target.value })} required />
            </label>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">{t("editModal.email")}</span>
                <input type="email" value={newMember.email} onChange={(event) => setNewMember({ ...newMember, email: event.target.value, invite: event.target.value.trim() ? newMember.invite : false })} />
              </label>
              <label className="field-stack">
                <span className="field-label">{t("editModal.joinedAt")}</span>
                <DateInput value={newMember.joined_at} onChange={(value) => setNewMember({ ...newMember, joined_at: value })} />
              </label>
            </div>
            {templates.length ? (
              <div className="field-stack">
                <span className="field-label">{t("editModal.templates")}</span>
                <div className="participant-check-grid">
                  {templates.map((template) => {
                    const checked = newMember.template_ids.includes(template.id);
                    return (
                      <label key={template.id} className={`participant-check-card${checked ? " participant-check-card-active" : ""}`}>
                        <input type="checkbox" checked={checked} onChange={(event) => setNewMember({
                          ...newMember,
                          template_ids: event.target.checked ? [...newMember.template_ids, template.id] : newMember.template_ids.filter((id) => id !== template.id),
                        })} />
                        <div><strong>{template.name}</strong></div>
                      </label>
                    );
                  })}
                </div>
              </div>
            ) : null}
            {permissions.financeManage ? (
              <label className="field-stack">
                <span className="field-label">{t("person.tariff")}</span>
                <Select value={newMember.tariff_id} onChange={(event) => setNewMember({ ...newMember, tariff_id: event.target.value })}>
                  <option value="">{t("person.tariffStandard", { name: defaultTariffName })}</option>
                  {tariffs.filter((tariff) => !tariff.is_default).map((tariff) => <option key={tariff.id} value={tariff.id}>{tariff.name}</option>)}
                </Select>
              </label>
            ) : null}
            {permissions.access && inviteAvailable ? (
              <label className="checkbox-line">
                <input type="checkbox" checked={newMember.invite} disabled={!newMember.email.trim()} onChange={(event) => setNewMember({ ...newMember, invite: event.target.checked })} />
                <span>
                  {t("newMember.invite")}
                  <span className="field-help"> {newMember.email.trim() ? t("newMember.inviteHelp") : t("invite.needsEmail")}</span>
                </span>
              </label>
            ) : null}
            {permissions.access && !inviteAvailable ? <span className="field-help">{t("invite.mailOff")}</span> : null}
            {permissions.access && newMember.invite ? (
              <label className="field-stack">
                <span className="field-label">{t("newMember.role")}</span>
                <Select value={newMember.role_id} onChange={(event) => setNewMember({ ...newMember, role_id: event.target.value })}>
                  {roles.map((role) => <option key={role.id} value={role.id}>{roleName(role, tNav)}</option>)}
                </Select>
              </label>
            ) : null}
            <div className="modal-actions">
              {!newMember.display_name.trim() ? <span className="field-help">{t("person.blockers.displayName")}</span> : null}
              <button type="button" className="button-ghost" onClick={() => setNewMember(null)}>{t("csvPreview.cancel")}</button>
              <button data-modal-save type="submit" className="button-primary" disabled={creating || !newMember.display_name.trim()}>
                {newMember.invite ? t("newMember.createAndInvite") : t("editModal.create")}
              </button>
            </div>
          </ModalSaveForm>
        ) : null}
      </Modal>

      <Modal open={bulkModal === "invite"} onClose={() => setBulkModal(null)} title={t("bulk.inviteTitle", { count: selectionCount })} description={t("bulk.inviteDescription")}>
        <div className="grid">
          <label className="field-stack">
            <span className="field-label">{t("bulk.inviteRole")}</span>
            <Select value={bulkRoleId} onChange={(event) => setBulkRoleId(event.target.value)}>
              {roles.map((role) => <option key={role.id} value={role.id}>{roleName(role, tNav)}</option>)}
            </Select>
            <span className="field-help">{t("bulk.inviteRoleHelp")}</span>
          </label>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setBulkModal(null)}>{t("csvPreview.cancel")}</button>
            <button type="button" className="button-primary" disabled={bulkBusy} onClick={() => void bulkInvite()}>{t("bulk.invite")}</button>
          </div>
        </div>
      </Modal>

      <Modal open={bulkModal === "tariff"} onClose={() => setBulkModal(null)} title={t("bulk.tariffTitle", { count: selectionCount })} description={t("bulk.tariffDescription")}>
        <div className="grid">
          <label className="field-stack">
            <span className="field-label">{t("person.tariff")}</span>
            <Select value={bulkTariff} onChange={(event) => setBulkTariff(event.target.value)}>
              <option value="">{t("person.tariffStandard", { name: defaultTariffName })}</option>
              {tariffs.filter((tariff) => !tariff.is_default).map((tariff) => <option key={tariff.id} value={tariff.id}>{tariff.name}</option>)}
            </Select>
          </label>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setBulkModal(null)}>{t("csvPreview.cancel")}</button>
            <button type="button" className="button-primary" disabled={bulkBusy} onClick={() => void bulkSetTariff()}>{t("bulk.setTariff")}</button>
          </div>
        </div>
      </Modal>

      <Modal open={bulkModal === "roles"} onClose={() => setBulkModal(null)} title={t("bulk.rolesTitle", { count: selectionCount })} description={t("bulk.rolesDescription")}>
        <div className="grid">
          <div className="field-stack" role="radiogroup" aria-label={t("bulk.rolesMode")}>
            <label className="field-radio-option">
              <input type="radio" name="bulk-roles-mode" checked={bulkRolesMode === "add"} onChange={() => setBulkRolesMode("add")} />
              {t("bulk.rolesAdd")}
            </label>
            <label className="field-radio-option">
              <input type="radio" name="bulk-roles-mode" checked={bulkRolesMode === "remove"} onChange={() => setBulkRolesMode("remove")} />
              {t("bulk.rolesRemove")}
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">{t("bulk.role")}</span>
            <Select value={bulkRoleId} onChange={(event) => setBulkRoleId(event.target.value)}>
              {roles.map((role) => <option key={role.id} value={role.id}>{roleName(role, tNav)}</option>)}
            </Select>
          </label>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setBulkModal(null)}>{t("csvPreview.cancel")}</button>
            <button type="button" className="button-primary" disabled={bulkBusy || !bulkRoleId} onClick={() => void bulkRoles()}>
              {bulkRolesMode === "add" ? t("bulk.rolesAdd") : t("bulk.rolesRemove")}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
