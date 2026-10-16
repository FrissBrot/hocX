"use client";

import { ChangeEvent, FormEvent, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { ActionIcon } from "@/components/ui/action-icons";
import { ActionMenu } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { DataTable } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch, LONG_RUNNING_TIMEOUT_MS } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { formatDate } from "@/lib/utils/format";
import { ParticipantSummary, TemplateSummary } from "@/types/api";

const PAGE_SIZE = 50;

type CsvPreviewRow = { display_name: string; first_name: string | null; last_name: string | null; email: string | null };
type ImportResult = { imported: ParticipantSummary[]; duplicates: string[]; errors: string[] };

function parseCsvForPreview(text: string): CsvPreviewRow[] {
  const normalized = text.replace(/^﻿/, "");
  const lines = normalized.split(/\r?\n/);
  const firstLine = lines[0] ?? "";
  const delimiter = firstLine.split(";").length > firstLine.split(",").length ? ";" : ",";
  const headers = firstLine.split(delimiter).map((h) => h.trim());
  const rows: CsvPreviewRow[] = [];
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    const cells = line.split(delimiter);
    const get = (name: string) => (cells[headers.indexOf(name)] ?? "").trim() || null;
    const first_name = get("Vorname");
    const last_name = get("Nachname");
    const nickname = get("Übername");
    const company_name = get("Firmenname");
    const email = get("Haupt-E-Mail");
    const display_name = nickname ?? ([first_name, last_name].filter(Boolean).join(" ") || null) ?? company_name;
    if (!display_name) continue;
    rows.push({ display_name, first_name, last_name, email });
  }
  return rows;
}

type ParticipantManagerProps = {
  initialParticipants: ParticipantSummary[];
  templates: TemplateSummary[];
  tenantId: string | null;
  canAdmin?: boolean;
};

type ParticipantFormState = {
  first_name: string;
  last_name: string;
  display_name: string;
  email: string;
  is_active: boolean;
  joined_at: string;
  left_at: string;
  login_enabled: boolean;
  password: string;
};

const emptyForm: ParticipantFormState = {
  first_name: "",
  last_name: "",
  display_name: "",
  email: "",
  is_active: true,
  joined_at: "",
  left_at: "",
  login_enabled: false,
  password: "",
};

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

type StatusFilter = "all" | "active" | "inactive" | "left";
type MembershipTone = "success" | "warning" | "info" | "neutral";

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

/** Initialen bevorzugt aus Vor-/Nachname (Übernamen wie "Kiwi" sagen wenig), sonst aus dem Anzeigenamen. */
function participantInitials(participant: ParticipantSummary): string {
  if (participant.first_name && participant.last_name) {
    return (participant.first_name[0] + participant.last_name[0]).toUpperCase();
  }
  const parts = participant.display_name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** Stabiler Farbton (0-4) aus der ID, damit ein Avatar beim Umbenennen seine Farbe behält. */
function avatarTone(key: string): number {
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) hash = (hash * 31 + key.charCodeAt(i)) | 0;
  return Math.abs(hash) % 5;
}

export function ParticipantManager({ initialParticipants, templates, tenantId, canAdmin = false }: ParticipantManagerProps) {
  const t = useTranslations("participants");
  const tUsers = useTranslations("users");
  const showToast = useToast();
  const confirm = useConfirm();
  const [participants, setParticipants] = useState(initialParticipants);
  const [selectedParticipant, setSelectedParticipant] = useState<ParticipantSummary | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [search, setSearch] = useState("");
  const [loginTab, setLoginTab] = useState<"withoutLogin" | "withLogin">("withoutLogin");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");
  const csvInputRef = useRef<HTMLInputElement>(null);
  const [form, setForm] = useState<ParticipantFormState>(emptyForm);
  const [selectedParticipantIds, setSelectedParticipantIds] = useState<string[]>([]);
  const [assignedTemplateIds, setAssignedTemplateIds] = useState<string[]>([]);
  const [csvPreview, setCsvPreview] = useState<{ rows: CsvPreviewRow[]; file: File } | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [importing, setImporting] = useState(false);

  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [hasMore, setHasMore] = useState(initialParticipants.length === PAGE_SIZE);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  async function loadMore() {
    setIsLoadingMore(true);
    try {
      const next = await browserApiFetch<ParticipantSummary[]>(`/api/participants?skip=${participants.length}&limit=${PAGE_SIZE}`);
      setParticipants((current) => [...current, ...(next ?? [])]);
      setHasMore((next ?? []).length === PAGE_SIZE);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.loadMoreFailed"), "error");
    } finally {
      setIsLoadingMore(false);
    }
  }

  const loadMoreSentinelRef = useInfiniteScroll({
    hasMore,
    isLoading: isLoadingMore,
    onLoadMore: () => void loadMore(),
  });

  const today = todayIso();

  const statusCounts = useMemo(() => {
    const group = participants.filter((participant) => Boolean(participant.login_enabled) === (loginTab === "withLogin"));
    const counts = { all: group.length, active: 0, inactive: 0, left: 0 };
    for (const participant of group) counts[participantCategory(participant, today)] += 1;
    return counts;
  }, [participants, today, loginTab]);

  const filteredParticipants = useMemo(() => {
    const dir = sortDirection === "asc" ? 1 : -1;
    const query = search.trim().toLowerCase();
    return participants
      .filter((participant) => Boolean(participant.login_enabled) === (loginTab === "withLogin"))
      .filter((participant) => statusFilter === "all" || participantCategory(participant, today) === statusFilter)
      .filter((participant) => {
        const haystack = `${participant.display_name} ${participant.first_name ?? ""} ${participant.last_name ?? ""} ${participant.email ?? ""}`.toLowerCase();
        return !query || haystack.includes(query);
      })
      .sort((a, b) => a.display_name.toLowerCase().localeCompare(b.display_name.toLowerCase()) * dir);
  }, [participants, search, statusFilter, sortDirection, today, loginTab]);

  const visibleIds = filteredParticipants.map((participant) => participant.id);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedParticipantIds.includes(id));
  const someVisibleSelected = !allVisibleSelected && visibleIds.some((id) => selectedParticipantIds.includes(id));

  function toggleSelectAllVisible(checked: boolean) {
    setSelectedParticipantIds((current) =>
      checked ? [...new Set([...current, ...visibleIds])] : current.filter((id) => !visibleIds.includes(id))
    );
  }

  function openCreate() {
    setSelectedParticipant(null);
    setForm(emptyForm);
    setAssignedTemplateIds([]);
    setShowModal(true);
  }

  async function openEdit(participant: ParticipantSummary) {
    setSelectedParticipant(participant);
    setForm({
      first_name: participant.first_name ?? "",
      last_name: participant.last_name ?? "",
      display_name: participant.display_name,
      email: participant.email ?? "",
      is_active: participant.is_active,
      joined_at: participant.joined_at ?? "",
      left_at: participant.left_at ?? "",
      login_enabled: Boolean(participant.login_enabled),
      password: "",
    });
    try {
      const assignedTemplates = await browserApiFetch<TemplateSummary[]>(`/api/participants/${participant.id}/templates`);
      setAssignedTemplateIds(assignedTemplates.map((template) => template.id));
    } catch (error) {
      setAssignedTemplateIds([]);
      showToast(
        error instanceof Error ? error.message : t("toasts.templatesLoadFailed"),
        "error"
      );
    }
    setShowModal(true);
  }

  const canSave = Boolean(form.display_name.trim()) && (!form.login_enabled || (Boolean(form.email.trim()) && (Boolean(selectedParticipant?.login_enabled) || form.password.length >= 12))) && (form.password.length === 0 || form.password.length >= 12);

  async function saveParticipant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (form.joined_at && form.left_at && form.left_at < form.joined_at) {
      showToast(t("toasts.leftBeforeJoined"), "error");
      return;
    }

    try {
      const payload = {
        first_name: form.first_name || null,
        last_name: form.last_name || null,
        display_name: form.display_name,
        email: form.email || null,
        is_active: form.is_active,
        joined_at: form.joined_at || null,
        left_at: form.left_at || null,
        ...(selectedParticipant && canAdmin ? {
          login_enabled: form.login_enabled,
          ...(form.password ? { password: form.password } : {}),
        } : {}),
      };

      let participantId: string;
      let updatedParticipant: ParticipantSummary;
      let successMessage = "";

      if (selectedParticipant) {
        updatedParticipant = await browserApiFetch<ParticipantSummary>(`/api/participants/${selectedParticipant.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        participantId = updatedParticipant.id;
        setParticipants((current) => current.map((item) => (item.id === updatedParticipant.id ? updatedParticipant : item)));
        successMessage = t("toasts.updated", { name: updatedParticipant.display_name });
      } else {
        updatedParticipant = await browserApiFetch<ParticipantSummary>("/api/participants", {
          method: "POST",
          body: JSON.stringify({ tenant_id: tenantId, ...payload }),
        });
        participantId = updatedParticipant.id;
        setParticipants((current) => [updatedParticipant, ...current]);
        successMessage = t("toasts.created", { name: updatedParticipant.display_name });
      }

      await browserApiFetch(`/api/participants/${participantId}/templates`, {
        method: "PUT",
        body: JSON.stringify({ template_ids: assignedTemplateIds }),
      });

      showToast(successMessage, "success");
      setShowModal(false);
      setSelectedParticipant(null);
      setForm(emptyForm);
      setAssignedTemplateIds([]);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.saveFailed"), "error");
    }
  }

  async function deleteParticipant(participantId: string) {
    const ok = await confirm({
      message: t("toasts.deleteConfirmMessage"),
      tone: "danger",
      confirmLabel: t("toasts.deleteConfirmLabel")
    });
    if (!ok) return;
    try {
      const deletedName = participants.find((participant) => participant.id === participantId)?.display_name ?? t("toasts.deleteUnnamed");
      await browserApiFetch(`/api/participants/${participantId}`, { method: "DELETE" });
      setParticipants((current) => current.filter((participant) => participant.id !== participantId));
      setSelectedParticipantIds((current) => current.filter((id) => id !== participantId));
      showToast(t("toasts.deletedSingle", { name: deletedName }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.deleteFailed"), "error");
    }
  }

  async function bulkDeleteParticipants() {
    if (!selectedParticipantIds.length) {
      return;
    }
    const ok = await confirm({
      message: t("toasts.bulkDeleteConfirmMessage", { count: selectedParticipantIds.length }),
      tone: "danger",
      confirmLabel: t("toasts.deleteConfirmLabel")
    });
    if (!ok) return;
    try {
      await browserApiFetch("/api/participants", {
        method: "DELETE",
        body: JSON.stringify({ participant_ids: selectedParticipantIds }),
      });
      setParticipants((current) => current.filter((participant) => !selectedParticipantIds.includes(participant.id)));
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
    const rows = parseCsvForPreview(text);
    setCsvPreview({ rows, file });
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
      setParticipants((current) => [...result.imported, ...current]);
      setCsvPreview(null);
      setImportResult(result);
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

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("pageTitle")}</h1>
          <p className="muted">{hasNoParticipants ? t("pageDescriptionEmpty") : t("pageDescription")}</p>
        </div>
        {hasNoParticipants ? null : (
        <div className="table-toolbar-actions">
          {selectedParticipantIds.length > 0 ? (
            <button type="button" className="button-secondary button-danger" onClick={() => void bulkDeleteParticipants()}>
              {t("deleteSelectionCount", { count: selectedParticipantIds.length })}
            </button>
          ) : null}
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
      <FilterTabs
        value={loginTab}
        onChange={(value) => { setLoginTab(value); setSelectedParticipantIds([]); }}
        options={[
          { value: "withoutLogin", label: t("loginTabs.withoutLogin"), count: participants.filter((p) => !p.login_enabled).length },
          { value: "withLogin", label: t("loginTabs.withLogin"), count: participants.filter((p) => p.login_enabled).length },
        ]}
      />
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
          { key: "email", label: t("columns.email") },
          { key: "membership", label: t("columns.membership") },
          { key: "is_active", label: t("columns.status") },
          { key: "actions", label: t("columns.actions"), header: <span className="participant-sr-only">{t("columns.actions")}</span> },
        ]}
        emptyMessage={t("emptyFiltered")}
        footer={
          <>
            <span>{t("footerCount", { count: filteredParticipants.length })}</span>
            <span>{t("footerHint")}</span>
          </>
        }
      >
        {filteredParticipants.map((participant) => {
          const isSelected = selectedParticipantIds.includes(participant.id);
          const fullName = [participant.first_name, participant.last_name].filter(Boolean).join(" ");
          const membership = membershipInfo(participant, today, t);
          return (
            <tr
              key={participant.id}
              className={`table-row-clickable${participant.is_active ? "" : " participant-row-inactive"}`}
              onClick={() => void openEdit(participant)}>
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
                    {fullName && fullName !== participant.display_name ? <span className="participant-name-sub">{fullName}</span> : null}
                  </div>
                </div>
              </td>
              <td>{participant.email ?? <span className="muted">{t("noEmail")}</span>}</td>
              <td>
                <span className={`participant-membership participant-membership-${membership.tone}`}>
                  <span className="participant-membership-dot" aria-hidden="true" />
                  {membership.label}
                </span>
              </td>
              <td>
                <Badge variant={participant.is_active ? "success" : "neutral"}>
                  {participant.is_active ? t("statusActive") : t("statusInactive")}
                </Badge>
              </td>
              <td>
                <div className="table-actions table-actions-end">
                  <ActionMenu
                    ariaLabel={t("rowActions", { name: participant.display_name })}
                    items={[
                      { label: t("edit"), onClick: () => void openEdit(participant) },
                      { label: t("delete"), onClick: () => void deleteParticipant(participant.id), danger: true },
                    ]}
                  />
                </div>
              </td>
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
          <DataTable columns={[t("csvPreview.displayName"), t("columns.firstName"), t("columns.lastName"), t("columns.email")]}>
            {(csvPreview?.rows ?? []).map((row, i) => (
              <tr key={i}>
                <td><strong>{row.display_name}</strong></td>
                <td>{row.first_name ?? <span className="muted">—</span>}</td>
                <td>{row.last_name ?? <span className="muted">—</span>}</td>
                <td>{row.email ?? <span className="muted">—</span>}</td>
              </tr>
            ))}
          </DataTable>
          <div className="table-toolbar-actions">
            <button type="button" className="button-secondary button-ghost" onClick={() => setCsvPreview(null)}>{t("csvPreview.cancel")}</button>
            <button type="button" className="button-secondary" onClick={() => void confirmCsvImport()} disabled={importing}>
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
                  {importResult.errors.map((e, i) => <div key={i}>{e}</div>)}
                </div>
              </div>
            )}
            <div className="table-toolbar-actions">
              <button type="button" className="button-secondary" onClick={() => setImportResult(null)}>{t("importResult.close")}</button>
            </div>
          </div>
        )}
      </Modal>

      {/* Edit/Create modal */}
      <Modal
        open={showModal}
        onClose={() => setShowModal(false)}
        title={selectedParticipant ? t("editModal.editTitle") : t("editModal.createTitle")}
        description={t("editModal.description")}
      >
        <ModalSaveForm className="grid" onSubmit={saveParticipant}>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("editModal.displayName")}</span>
              <input value={form.display_name} onChange={(event) => setForm((current) => ({ ...current, display_name: event.target.value }))} required />
            </label>
            <label className="checkbox-line">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))}
              />
              {t("editModal.active")}
            </label>
          </div>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("editModal.firstName")}</span>
              <input value={form.first_name} onChange={(event) => setForm((current) => ({ ...current, first_name: event.target.value }))} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("editModal.lastName")}</span>
              <input value={form.last_name} onChange={(event) => setForm((current) => ({ ...current, last_name: event.target.value }))} />
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">{t("editModal.email")}</span>
            <input value={form.email} onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))} />
          </label>
          {selectedParticipant && canAdmin ? (
            <>
              <label className="checkbox-line">
                <input type="checkbox" checked={form.login_enabled} onChange={(event) => setForm((current) => ({ ...current, login_enabled: event.target.checked }))} />
                {tUsers("enableLogin")}
              </label>
              {form.login_enabled ? (
                <label className="field-stack">
                  <span className="field-label">{tUsers("newPassword")}</span>
                  <input type="password" autoComplete="new-password" value={form.password} onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))} />
                  <span className="field-help">{tUsers("passwordHelpEdit")}</span>
                </label>
              ) : null}
            </>
          ) : null}
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("editModal.joinedAt")}</span>
              <DateInput value={form.joined_at} onChange={(value) => setForm((current) => ({ ...current, joined_at: value }))} />
              <span className="muted" style={{ fontSize: "var(--text-sm)" }}>
                {t("editModal.joinedAtHint")}
              </span>
            </label>
            <label className="field-stack">
              <span className="field-label">{t("editModal.leftAt")}</span>
              <DateInput value={form.left_at} onChange={(value) => setForm((current) => ({ ...current, left_at: value }))} />
              <span className="muted" style={{ fontSize: "var(--text-sm)" }}>
                {t("editModal.leftAtHint")}
              </span>
            </label>
          </div>
          <div className="field-stack">
            <span className="field-label">{t("editModal.templates")}</span>
            <div className="participant-check-grid">
              {templates.map((template) => {
                const checked = assignedTemplateIds.includes(template.id);
                return (
                  <label key={template.id} className={`participant-check-card${checked ? " participant-check-card-active" : ""}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(event) =>
                        setAssignedTemplateIds((current) =>
                          event.target.checked ? [...new Set([...current, template.id])] : current.filter((id) => id !== template.id)
                        )
                      }
                    />
                    <div>
                      <strong>{template.name}</strong>
                      <div className="muted">{template.description ?? t("editModal.noDescription")}</div>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
          <div className="table-toolbar-actions">
            <button data-modal-save type="submit" className="button-secondary" disabled={!canSave}>
              {selectedParticipant ? t("editModal.save") : t("editModal.create")}
            </button>
          </div>
        </ModalSaveForm>
      </Modal>
    </div>
  );
}
