"use client";

import { ChangeEvent, FormEvent, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { DataTable } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
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
};

type ParticipantFormState = {
  first_name: string;
  last_name: string;
  display_name: string;
  email: string;
  is_active: boolean;
  joined_at: string;
  left_at: string;
};

const emptyForm: ParticipantFormState = {
  first_name: "",
  last_name: "",
  display_name: "",
  email: "",
  is_active: true,
  joined_at: "",
  left_at: "",
};

/** "Ausgetreten (seit dd.mm.yyyy)" / "Noch nicht eingetreten (ab dd.mm.yyyy)" - membership-window
 * status derived from joined_at/left_at, shown alongside the existing is_active toggle since the
 * two are independent: is_active/inactive is a manual switch, join/leave dates gate which
 * protocols' attendance rosters a participant appears in. Plain helper (no component), so `t`
 * is passed in by the caller instead of calling useTranslations() here. */
function membershipStatus(participant: ParticipantSummary, t: (key: string, values?: Record<string, string | number | Date>) => string): string | null {
  const today = new Date().toISOString().slice(0, 10);
  // left_at is inclusive - the participant is still a member through the end of that day
  // itself (see participant_eligible_on / the help text "Erscheint ab dem Folgetag nicht
  // mehr in Anwesenheitslisten") - `<= today` showed the "Ausgetreten" badge one day
  // early, on left_at itself, contradicting that same help text (audit finding,
  // 2026-08-25).
  if (participant.left_at && participant.left_at < today) {
    return t("membership.leftSince", { date: formatDate(participant.left_at) });
  }
  if (participant.joined_at && participant.joined_at > today) {
    return t("membership.joinsFrom", { date: formatDate(participant.joined_at) });
  }
  return null;
}

export function ParticipantManager({ initialParticipants, templates, tenantId }: ParticipantManagerProps) {
  const t = useTranslations("participants");
  const showToast = useToast();
  const confirm = useConfirm();
  const [participants, setParticipants] = useState(initialParticipants);
  const [selectedParticipant, setSelectedParticipant] = useState<ParticipantSummary | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [search, setSearch] = useState("");
  const [form, setForm] = useState<ParticipantFormState>(emptyForm);
  const [selectedParticipantIds, setSelectedParticipantIds] = useState<string[]>([]);
  const [assignedTemplateIds, setAssignedTemplateIds] = useState<string[]>([]);
  const [csvPreview, setCsvPreview] = useState<{ rows: CsvPreviewRow[]; file: File } | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [importing, setImporting] = useState(false);

  const [sortKey, setSortKey] = useState<"display_name" | "first_name" | "last_name" | "email" | "is_active">("display_name");
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

  function toggleSort(key: typeof sortKey) {
    setSortKey((cur) => {
      if (cur === key) { setSortDirection((d) => d === "asc" ? "desc" : "asc"); return cur; }
      setSortDirection("asc");
      return key;
    });
  }

  const filteredParticipants = useMemo(() => {
    const dir = sortDirection === "asc" ? 1 : -1;
    return participants
      .filter((participant) => {
        const haystack = `${participant.display_name} ${participant.first_name ?? ""} ${participant.last_name ?? ""} ${participant.email ?? ""}`.toLowerCase();
        return !search || haystack.includes(search.toLowerCase());
      })
      .sort((a, b) => {
        if (sortKey === "is_active") return ((a.is_active ? 1 : 0) - (b.is_active ? 1 : 0)) * dir;
        const av = String(a[sortKey] ?? "").toLowerCase();
        const bv = String(b[sortKey] ?? "").toLowerCase();
        return av.localeCompare(bv) * dir;
      });
  }, [participants, search, sortKey, sortDirection]);

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
          <label className="button-secondary button-ghost participant-import-button">
            {t("csvImport")}
            <input type="file" accept=".csv,text/csv" onChange={(e) => void handleCsvFileSelected(e)} hidden />
          </label>
          <button
            type="button"
            className="button-secondary button-danger"
            onClick={() => void bulkDeleteParticipants()}
            disabled={selectedParticipantIds.length === 0}
          >
            {t("deleteSelection")}
          </button>
          <button type="button" className="button-secondary" onClick={openCreate}>
            {t("newParticipant")}
          </button>
        </div>
        )}
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
              <label className="button-secondary participant-import-button">
                {t("emptyState.importList")}
                <input type="file" accept=".csv,text/csv" onChange={(e) => void handleCsvFileSelected(e)} hidden />
              </label>
            </>
          }
        />
      ) : (
      <>
      <div className="list-filter-row">
        <div />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder={t("searchPlaceholder")} />
        </div>
      </div>

      <DataTable
        className="data-table-lg"
        columns={[
          "",
          { key: "display_name", label: t("columns.name"), sortable: true, sortDirection: sortKey === "display_name" ? sortDirection : null, onSort: () => toggleSort("display_name") },
          { key: "first_name", label: t("columns.firstName"), sortable: true, sortDirection: sortKey === "first_name" ? sortDirection : null, onSort: () => toggleSort("first_name") },
          { key: "last_name", label: t("columns.lastName"), sortable: true, sortDirection: sortKey === "last_name" ? sortDirection : null, onSort: () => toggleSort("last_name") },
          { key: "email", label: t("columns.email"), sortable: true, sortDirection: sortKey === "email" ? sortDirection : null, onSort: () => toggleSort("email") },
          { key: "is_active", label: t("columns.status"), sortable: true, sortDirection: sortKey === "is_active" ? sortDirection : null, onSort: () => toggleSort("is_active") },
          t("columns.actions"),
        ]}
        emptyMessage={t("emptyFiltered")}
      >
        {filteredParticipants.map((participant) => {
          const isSelected = selectedParticipantIds.includes(participant.id);
          return (
            <tr key={participant.id} className="table-row-clickable" onClick={() => void openEdit(participant)}>
              <td onClick={(event) => event.stopPropagation()}>
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={(event) =>
                    setSelectedParticipantIds((current) =>
                      event.target.checked ? [...current, participant.id] : current.filter((id) => id !== participant.id)
                    )
                  }
                />
              </td>
              <td>
                <strong>{participant.display_name}</strong>
                <div className="muted">
                  {[participant.first_name, participant.last_name].filter(Boolean).join(" ") || (participant.email ?? t("fallbackName"))}
                </div>
              </td>
              <td>{participant.first_name ?? "—"}</td>
              <td>{participant.last_name ?? "—"}</td>
              <td>{participant.email ?? "—"}</td>
              <td>
                <span className="pill">{participant.is_active ? t("statusActive") : t("statusInactive")}</span>
                {membershipStatus(participant, t) && <div className="muted">{membershipStatus(participant, t)}</div>}
              </td>
              <td>
                <div className="table-actions">
                  <button
                    type="button"
                    className="button-secondary button-danger"
                    onClick={(event) => {
                      event.stopPropagation();
                      void deleteParticipant(participant.id);
                    }}
                  >
                    {t("delete")}
                  </button>
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
            <button data-modal-save type="submit" className="button-secondary">
              {selectedParticipant ? t("editModal.save") : t("editModal.create")}
            </button>
          </div>
        </ModalSaveForm>
      </Modal>
    </div>
  );
}
