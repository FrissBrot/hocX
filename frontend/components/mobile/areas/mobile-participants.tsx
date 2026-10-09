"use client";

import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { useAllPages } from "@/components/mobile/mobile-data";
import { MobileIcon } from "@/components/mobile/mobile-icons";
import { useOpenMore } from "@/components/mobile/mobile-shell";
import {
  MobileAvatar,
  MobileChip,
  MobileChipRow,
  MobileEmpty,
  MobileFab,
  MobileListRow,
  MobileSelectionBar,
  MobileSubHeader,
  MobileSwitch,
} from "@/components/mobile/mobile-ui";
import { dateParts, todayIso } from "@/components/mobile/mobile-utils";
import { FileTypeTile } from "@/components/mobile/areas/mobile-files";
import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import type { ParticipantSummary, TemplateSummary } from "@/types/api";

type ImportResult = { imported: ParticipantSummary[]; duplicates: string[]; errors: string[] };
type StatusFilter = "active" | "inactive" | "all";

function membershipNote(participant: ParticipantSummary, t: (key: string, values?: Record<string, string>) => string, locale: string): string | null {
  const today = todayIso();
  if (participant.left_at && participant.left_at < today) return t("membership.leftSince", { date: dateParts.dayMonth(participant.left_at, locale) });
  if (participant.joined_at && participant.joined_at > today) return t("membership.joinsFrom", { date: dateParts.dayMonth(participant.joined_at, locale) });
  return null;
}

export function MobileParticipants({ initialParticipants, templates, tenantId }: { initialParticipants: ParticipantSummary[]; templates: TemplateSummary[]; tenantId: string | null }) {
  const t = useTranslations("participants");
  const tMobile = useTranslations("mobile");
  const locale = useLocale();
  const openMore = useOpenMore();
  const confirm = useConfirm();
  const showToast = useToast();
  const [participants, setParticipants] = useAllPages<ParticipantSummary>("/api/participants", initialParticipants);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("active");
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [editing, setEditing] = useState<ParticipantSummary | "new" | null>(null);
  const [importing, setImporting] = useState(false);

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return participants
      .filter((participant) => (status === "all" ? true : status === "active" ? participant.is_active : !participant.is_active))
      .filter((participant) => !needle || `${participant.display_name} ${participant.email ?? ""}`.toLowerCase().includes(needle))
      .sort((a, b) => a.display_name.localeCompare(b.display_name));
  }, [participants, search, status]);

  function toggle(id: string) {
    setSelected((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  }

  async function bulkDelete() {
    if (!selected.length || !(await confirm({ message: t("toasts.bulkDeleteConfirmMessage", { count: selected.length }), tone: "danger", confirmLabel: t("toasts.deleteConfirmLabel") }))) return;
    try {
      await browserApiFetch("/api/participants", { method: "DELETE", body: JSON.stringify({ participant_ids: selected }) });
      setParticipants((list) => list.filter((participant) => !selected.includes(participant.id)));
      setSelected([]);
      setSelecting(false);
      showToast(t("toasts.bulkDeleted"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.bulkDeleteFailed"), "error");
    }
  }

  return (
    <div className="mobile-page mobile-page-list">
      <MobileSubHeader
        title={selecting ? tMobile("participants.selected", { count: selected.length }) : t("pageTitle")}
        subtitle={selecting ? undefined : t("pageDescriptionEmpty")}
        backLabel={selecting ? tMobile("editor.done") : tMobile("tabs.more")}
        onBack={
          selecting
            ? () => {
                setSelecting(false);
                setSelected([]);
              }
            : openMore
        }
        actions={
          selecting ? undefined : (
            <>
              <button type="button" className="mobile-icon-button" aria-label={tMobile("participants.select")} onClick={() => setSelecting(true)}>
                <MobileIcon name="check" />
              </button>
              <button type="button" className="mobile-icon-button" aria-label={t("csvImport")} onClick={() => setImporting(true)}>
                <MobileIcon name="document" />
              </button>
            </>
          )
        }
      />
      <div className="mobile-section">
        <SearchInput value={search} onChange={setSearch} placeholder={t("searchPlaceholder")} />
      </div>
      <MobileChipRow>
        {(["active", "inactive", "all"] as StatusFilter[]).map((value) => (
          <MobileChip key={value} active={status === value} onClick={() => setStatus(value)}>
            {value === "active" ? t("statusActive") : value === "inactive" ? t("statusInactive") : tMobile("common.all")}
          </MobileChip>
        ))}
      </MobileChipRow>
      {visible.length > 0 ? (
        <div className="mobile-section">
          <div className="mobile-card mobile-list-card">
            {visible.map((participant) => {
              const note = membershipNote(participant, t, locale);
              const isSelected = selected.includes(participant.id);
              return (
                <MobileListRow
                  key={participant.id}
                  onClick={() => (selecting ? toggle(participant.id) : setEditing(participant))}
                  chevron={!selecting}
                  leading={
                    <>
                      {selecting ? (
                        <span className={`mobile-check${isSelected ? " mobile-check-on" : ""}`} aria-hidden="true">
                          {isSelected ? <MobileIcon name="check" size={14} strokeWidth={3} /> : null}
                        </span>
                      ) : null}
                      <MobileAvatar name={participant.display_name} size="md" />
                    </>
                  }
                  label={
                    <span className="mobile-row-stack">
                      <span className="mobile-row-title">{participant.display_name}</span>
                      <span className="mobile-row-meta">{note ?? participant.email ?? ""}</span>
                    </span>
                  }
                  trailing={!participant.is_active ? <span className="mobile-status-pill">{t("statusInactive")}</span> : undefined}
                />
              );
            })}
          </div>
        </div>
      ) : (
        <MobileEmpty title={participants.length ? t("emptyFiltered") : t("emptyState.title")} hint={participants.length ? undefined : t("emptyState.description")} />
      )}

      {selecting ? (
        <MobileSelectionBar label={tMobile("participants.selectedCount", { count: selected.length })}>
          <button type="button" disabled={!selected.length} onClick={() => void bulkDelete()}>
            {t("delete")}
          </button>
        </MobileSelectionBar>
      ) : (
        <MobileFab label={tMobile("participants.fab")} onClick={() => setEditing("new")} />
      )}

      {editing ? (
        <ParticipantSheet
          participant={editing === "new" ? null : editing}
          templates={templates}
          tenantId={tenantId}
          onClose={() => setEditing(null)}
          onSaved={(saved, created) => {
            setParticipants((list) => (created ? [saved, ...list] : list.map((item) => (item.id === saved.id ? saved : item))));
            setEditing(null);
          }}
          onDeleted={(id) => {
            setParticipants((list) => list.filter((item) => item.id !== id));
            setEditing(null);
          }}
        />
      ) : null}
      {importing ? (
        <ImportSheet
          onClose={() => setImporting(false)}
          onImported={(result) => setParticipants((list) => [...result.imported, ...list])}
        />
      ) : null}
    </div>
  );
}

function ParticipantSheet({
  participant,
  templates,
  tenantId,
  onClose,
  onSaved,
  onDeleted,
}: {
  participant: ParticipantSummary | null;
  templates: TemplateSummary[];
  tenantId: string | null;
  onClose: () => void;
  onSaved: (participant: ParticipantSummary, created: boolean) => void;
  onDeleted: (id: string) => void;
}) {
  const t = useTranslations("participants");
  const tMobile = useTranslations("mobile");
  const confirm = useConfirm();
  const showToast = useToast();
  const [form, setForm] = useState({
    first_name: participant?.first_name ?? "",
    last_name: participant?.last_name ?? "",
    display_name: participant?.display_name ?? "",
    email: participant?.email ?? "",
    is_active: participant?.is_active ?? true,
    joined_at: participant?.joined_at ?? "",
    left_at: participant?.left_at ?? "",
  });
  const [templateIds, setTemplateIds] = useState<string[] | null>(participant ? null : []);
  const [saving, setSaving] = useState(false);
  const update = (patch: Partial<typeof form>) => setForm((current) => ({ ...current, ...patch }));
  const displayName = form.display_name.trim() || [form.first_name, form.last_name].filter(Boolean).join(" ").trim();

  useEffect(() => {
    if (!participant) return;
    let cancelled = false;
    browserApiFetch<TemplateSummary[]>(`/api/participants/${participant.id}/templates`)
      .then((list) => {
        if (!cancelled) setTemplateIds((list ?? []).map((template) => template.id));
      })
      .catch(() => {
        if (cancelled) return;
        setTemplateIds([]);
        showToast(t("toasts.templatesLoadFailed"), "error");
      });
    return () => {
      cancelled = true;
    };
  }, [participant, showToast, t]);

  async function save() {
    if (!displayName || saving) return;
    if (form.joined_at && form.left_at && form.left_at < form.joined_at) {
      showToast(t("toasts.leftBeforeJoined"), "error");
      return;
    }
    setSaving(true);
    const payload = {
      first_name: form.first_name || null,
      last_name: form.last_name || null,
      display_name: displayName,
      email: form.email || null,
      is_active: form.is_active,
      joined_at: form.joined_at || null,
      left_at: form.left_at || null,
    };
    try {
      const saved = participant
        ? await browserApiFetch<ParticipantSummary>(`/api/participants/${participant.id}`, { method: "PATCH", body: JSON.stringify(payload) })
        : await browserApiFetch<ParticipantSummary>("/api/participants", { method: "POST", body: JSON.stringify({ tenant_id: tenantId, ...payload }) });
      if (templateIds) {
        await browserApiFetch(`/api/participants/${saved.id}/templates`, { method: "PUT", body: JSON.stringify({ template_ids: templateIds }) });
      }
      showToast(participant ? t("toasts.updated", { name: saved.display_name }) : t("toasts.created", { name: saved.display_name }), "success");
      onSaved(saved, !participant);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.saveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!participant || !(await confirm({ message: t("toasts.deleteConfirmMessage"), tone: "danger", confirmLabel: t("toasts.deleteConfirmLabel") }))) return;
    try {
      await browserApiFetch(`/api/participants/${participant.id}`, { method: "DELETE" });
      showToast(t("toasts.deletedSingle", { name: participant.display_name }), "success");
      onDeleted(participant.id);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.deleteFailed"), "error");
    }
  }

  return (
    <Modal
      open
      size="sheet"
      title={participant ? t("editModal.editTitle") : t("editModal.createTitle")}
      onClose={onClose}
      className="mobile-sheet"
      footer={
        <div className="modal-actions mobile-sheet-footer">
          {participant ? (
            <button type="button" className="button-danger" onClick={() => void remove()}>
              {t("delete")}
            </button>
          ) : (
            <button type="button" className="button-ghost" onClick={onClose}>
              {tMobile("common.cancel")}
            </button>
          )}
          <button type="button" className="button-primary" data-modal-save disabled={!displayName || saving} onClick={() => void save()}>
            {participant ? t("editModal.save") : t("editModal.create")}
          </button>
        </div>
      }
    >
      <div className="grid mobile-sheet-body">
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">{t("editModal.firstName")}</span>
            <input value={form.first_name} onChange={(event) => update({ first_name: event.target.value })} />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("editModal.lastName")}</span>
            <input value={form.last_name} onChange={(event) => update({ last_name: event.target.value })} />
          </label>
        </div>
        <label className="field-stack">
          <span className="field-label">{t("editModal.displayName")}</span>
          <input value={form.display_name} placeholder={displayName} onChange={(event) => update({ display_name: event.target.value })} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("editModal.email")}</span>
          <input type="email" inputMode="email" value={form.email} onChange={(event) => update({ email: event.target.value })} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("editModal.joinedAt")}</span>
          <DateInput value={form.joined_at} onChange={(value) => update({ joined_at: value })} />
          <span className="field-help">{t("editModal.joinedAtHint")}</span>
        </label>
        <label className="field-stack">
          <span className="field-label">{t("editModal.leftAt")}</span>
          <DateInput value={form.left_at} min={form.joined_at || undefined} onChange={(value) => update({ left_at: value })} />
          <span className="field-help">{t("editModal.leftAtHint")}</span>
        </label>
        <div className="mobile-card mobile-group-card">
          <button type="button" className="mobile-list-row" aria-pressed={form.is_active} onClick={() => update({ is_active: !form.is_active })}>
            <span className="mobile-list-row-label">{t("editModal.active")}</span>
            <MobileSwitch checked={form.is_active} />
          </button>
        </div>
        {templates.length > 0 ? (
          <div className="field-stack">
            <span className="field-label">{t("editModal.templates")}</span>
            <div className="mobile-card mobile-group-card">
              {templates.map((template) => {
                const on = templateIds?.includes(template.id) ?? false;
                return (
                  <button
                    key={template.id}
                    type="button"
                    className="mobile-list-row"
                    aria-pressed={on}
                    disabled={templateIds === null}
                    onClick={() => setTemplateIds((current) => (current ?? []).includes(template.id) ? (current ?? []).filter((id) => id !== template.id) : [...(current ?? []), template.id])}
                  >
                    <span className={`mobile-check mobile-check-square${on ? " mobile-check-on" : ""}`}>{on ? <MobileIcon name="check" size={14} strokeWidth={3} /> : null}</span>
                    <span className="mobile-list-row-label">{template.name}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}

function ImportSheet({ onClose, onImported }: { onClose: () => void; onImported: (result: ImportResult) => void }) {
  const t = useTranslations("participants");
  const tMobile = useTranslations("mobile");
  const showToast = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [rowCount, setRowCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);

  async function pick(event: ChangeEvent<HTMLInputElement>) {
    const chosen = event.target.files?.[0] ?? null;
    event.target.value = "";
    if (!chosen) return;
    const lines = (await chosen.text()).split(/\r?\n/).filter((line) => line.trim());
    setFile(chosen);
    setRowCount(Math.max(0, lines.length - 1));
  }

  async function runImport() {
    if (!file || busy) return;
    setBusy(true);
    try {
      const body = new FormData();
      body.append("file", file);
      const imported = await browserApiFetch<ImportResult>("/api/participants/import-csv", { method: "POST", body });
      setResult(imported);
      onImported(imported);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.csvImportFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      size="sheet"
      title={result ? t("importResult.title") : t("emptyState.importList")}
      onClose={onClose}
      className="mobile-sheet"
      footer={
        <div className="modal-actions mobile-sheet-footer">
          <button type="button" className="button-ghost" onClick={onClose}>
            {result ? t("importResult.close") : t("csvPreview.cancel")}
          </button>
          {!result ? (
            <button type="button" className="button-primary" disabled={!file || busy} onClick={() => void runImport()}>
              {busy ? t("csvPreview.importing") : t("csvPreview.importEntries", { count: rowCount })}
            </button>
          ) : null}
        </div>
      }
    >
      <div className="grid mobile-sheet-body">
        <input ref={inputRef} type="file" accept=".csv,text/csv" hidden onChange={(event) => void pick(event)} />
        {result ? (
          <div className="mobile-card mobile-group-card">
            <MobileListRow label={t("importResult.imported", { count: result.imported.length })} />
            <MobileListRow label={t("importResult.duplicatesSkipped", { count: result.duplicates.length })} />
            <MobileListRow label={t("importResult.errorsCount", { count: result.errors.length })} />
          </div>
        ) : file ? (
          <div className="mobile-card mobile-group-card">
            <MobileListRow
              leading={<FileTypeTile name={file.name} />}
              label={
                <span className="mobile-row-stack">
                  <span className="mobile-row-title">{file.name}</span>
                  <span className="mobile-row-meta">{t("csvPreview.description", { count: rowCount })}</span>
                </span>
              }
              onClick={() => inputRef.current?.click()}
            />
          </div>
        ) : (
          <button type="button" className="button-secondary mobile-button-block" onClick={() => inputRef.current?.click()}>
            {tMobile("participants.chooseCsv")}
          </button>
        )}
      </div>
    </Modal>
  );
}
