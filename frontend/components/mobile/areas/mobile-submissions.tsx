"use client";

import { useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MobileIcon } from "@/components/mobile/mobile-icons";
import { useOpenMore } from "@/components/mobile/mobile-shell";
import {
  MobileActionSheet,
  MobileAvatar,
  MobileChip,
  MobileChipRow,
  MobileEmpty,
  MobileFab,
  MobileListRow,
  MobileProgress,
  MobileSubHeader,
} from "@/components/mobile/mobile-ui";
import { dateParts } from "@/components/mobile/mobile-utils";
import { FileTypeTile } from "@/components/mobile/areas/mobile-files";
import {
  assignmentPayload,
  formFromAssignment,
  FormState,
  initialForm,
  SubmissionAssignmentFormModal,
} from "@/components/submission-assignments/submission-assignment-form";
import { SubmissionLinkManager } from "@/components/submission-assignments/submission-link-manager";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatFileSize } from "@/lib/utils/format";
import type {
  AssignmentSummary,
  CycleConfigSummary,
  EventSummary,
  ParticipantSummary,
  StructuredListDefinition,
  SubmissionAssignment,
  SubmissionElementStatusEntry,
  SubmissionLink,
  SubmissionUploadLogEntry,
} from "@/types/api";

type ElementFilter = "all" | "submitted" | "open" | "quarantine";

function elementState(element: SubmissionElementStatusEntry): "submitted" | "quarantine" | "closed" | "open" | "missed" | "pending" {
  if (element.status === "closed") return "closed";
  if (element.status === "submitted") return element.files.some((file) => file.scan_status === "pending" || file.scan_status === "error") ? "quarantine" : "submitted";
  const now = new Date();
  if (element.window_end && now > new Date(element.window_end)) return "missed";
  if (element.window_start && now < new Date(element.window_start)) return "pending";
  return "open";
}

async function download(path: string, filename: string) {
  const response = await fetch(path.startsWith("http") ? path : `${browserApiBaseUrl}${path}`, { credentials: "include" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function MobileSubmissions({
  initialAssignments,
  initialLinks,
  availableLists,
  availableEvents,
  availableParticipants,
  availableCycleConfigs,
  tenantName,
}: {
  initialAssignments: SubmissionAssignment[];
  initialLinks: SubmissionLink[];
  availableLists: StructuredListDefinition[];
  availableEvents: EventSummary[];
  availableParticipants: ParticipantSummary[];
  availableCycleConfigs: CycleConfigSummary[];
  tenantName: string | null;
}) {
  const t = useTranslations("submissionAssignments");
  const tMobile = useTranslations("mobile");
  const locale = useLocale();
  const openMore = useOpenMore();
  const confirm = useConfirm();
  const showToast = useToast();
  const [assignments, setAssignments] = useState(initialAssignments);
  const [links, setLinks] = useState(initialLinks);
  const [summaries, setSummaries] = useState<Record<string, AssignmentSummary>>({});
  const [clamav, setClamav] = useState<"online" | "offline" | "unknown">("unknown");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [elements, setElements] = useState<SubmissionElementStatusEntry[]>([]);
  const [elementFilter, setElementFilter] = useState<ElementFilter>("all");
  const [openElement, setOpenElement] = useState<SubmissionElementStatusEntry | null>(null);
  const [log, setLog] = useState<SubmissionUploadLogEntry[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(initialForm);
  const [linksOpen, setLinksOpen] = useState(false);
  const [actionsOpen, setActionsOpen] = useState(false);
  const availableTags = useMemo(() => [...new Set(availableEvents.map((event) => event.tag).filter((tag): tag is string => !!tag))].sort(), [availableEvents]);
  const participantName = (id: string | null) => (id ? availableParticipants.find((participant) => participant.id === id)?.display_name ?? null : null);
  const selected = assignments.find((assignment) => assignment.id === selectedId) ?? null;
  const logLabels: Record<string, string> = {
    upload_received: t("logUploadReceived"),
    quarantined: t("logQuarantined"),
    moved_to_storage: t("logMovedToStorage"),
    submitted: t("logSubmitted"),
    captcha_failed: t("logCaptchaFailed"),
    validation_failed: t("logValidationFailed"),
    element_closed: t("logElementClosed"),
    upload_error: t("logUploadError"),
    scan_clean: t("logScanClean"),
    scan_pending: t("logScanPending"),
    scan_infected: t("logScanInfected"),
    rescan_clean: t("logRescanClean"),
    rescan_infected: t("logRescanInfected"),
    rescan_pending: t("logRescanPending"),
  };

  useEffect(() => {
    browserApiFetch<{ status: string }>("/api/clamav/status").then(
      (status) => setClamav(status.status === "online" ? "online" : "offline"),
      () => setClamav("offline")
    );
    void Promise.all(
      initialAssignments.map((assignment) =>
        browserApiFetch<AssignmentSummary>(`/api/submission-assignments/${assignment.id}/summary`)
          .then((summary) => [assignment.id, summary] as const)
          .catch(() => null)
      )
    ).then((pairs) => setSummaries(Object.fromEntries(pairs.filter((pair): pair is readonly [string, AssignmentSummary] => !!pair))));
  }, [initialAssignments]);

  function sourceMeta(assignment: SubmissionAssignment): string {
    if (assignment.source_type === "events") {
      const window = [
        assignment.offset_days_before != null ? t("fromDaysBefore", { count: assignment.offset_days_before }) : null,
        assignment.offset_days_after != null ? t("untilDaysAfter", { count: assignment.offset_days_after }) : null,
      ].filter(Boolean);
      return [assignment.tag_filter ? t("sourceEventTagged", { tag: assignment.tag_filter }) : t("sourceEvents"), window.join(" – ") || null].filter(Boolean).join(" · ");
    }
    const deadline = assignment.deadline ? t("deadlineNamed", { date: dateParts.dayMonth(assignment.deadline.slice(0, 10), locale) }) : t("noDeadlineOpenUntilClosed");
    if (assignment.source_type === "list") {
      const list = availableLists.find((item) => item.id === assignment.list_definition_id);
      return `${list ? t("sourceListNamed", { name: list.name }) : t("sourceList")} · ${deadline}`;
    }
    return `${t("sourceManual")} · ${deadline}`;
  }

  async function openAssignment(assignment: SubmissionAssignment) {
    setSelectedId(assignment.id);
    setElements([]);
    setElementFilter("all");
    try {
      setElements((await browserApiFetch<SubmissionElementStatusEntry[]>(`/api/submission-assignments/${assignment.id}/elements`)) ?? []);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("elementsLoadFailed"), "error");
    }
  }

  async function openElementSheet(element: SubmissionElementStatusEntry) {
    if (!selected) return;
    setOpenElement(element);
    setLog([]);
    try {
      setLog((await browserApiFetch<SubmissionUploadLogEntry[]>(`/api/submission-assignments/${selected.id}/upload-log?element_ref=${encodeURIComponent(element.element_ref)}`)) ?? []);
    } catch {
      showToast(t("logLoadFailed"), "error");
    }
  }

  async function setElementOpen(element: SubmissionElementStatusEntry, reopen: boolean) {
    if (!selected) return;
    try {
      const updated = await browserApiFetch<SubmissionElementStatusEntry>(
        `/api/submission-assignments/${selected.id}/elements/${element.element_ref}/${reopen ? "reopen" : "close"}`,
        { method: "POST" }
      );
      setElements((list) => list.map((item) => (item.element_ref === element.element_ref ? updated : item)));
      setOpenElement(updated);
      showToast(reopen ? t("elementReopenedToast") : t("elementClosedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : reopen ? t("elementReopenFailed") : t("elementCloseFailed"), "error");
    }
  }

  async function save() {
    try {
      const body = JSON.stringify(assignmentPayload(form));
      const saved = editingId
        ? await browserApiFetch<SubmissionAssignment>(`/api/submission-assignments/${editingId}`, { method: "PATCH", body })
        : await browserApiFetch<SubmissionAssignment>("/api/submission-assignments", { method: "POST", body });
      setAssignments((list) => (editingId ? list.map((item) => (item.id === saved.id ? saved : item)) : [saved, ...list]));
      setFormOpen(false);
      showToast(editingId ? t("assignmentSavedToast") : t("assignmentCreatedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("assignmentSaveFailed"), "error");
    }
  }

  async function remove(assignment: SubmissionAssignment) {
    if (!(await confirm({ message: t("deleteAssignmentConfirm"), tone: "danger", confirmLabel: t("delete") }))) return;
    try {
      await browserApiFetch(`/api/submission-assignments/${assignment.id}`, { method: "DELETE" });
      setAssignments((list) => list.filter((item) => item.id !== assignment.id));
      setSelectedId(null);
      showToast(t("assignmentDeletedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("assignmentDeleteFailed"), "error");
    }
  }

  const shared = (
    <>
      <SubmissionAssignmentFormModal
        open={formOpen}
        editing={editingId !== null}
        tenantName={tenantName}
        form={form}
        setForm={setForm}
        links={links}
        availableLists={availableLists}
        availableTags={availableTags}
        availableCycleConfigs={availableCycleConfigs}
        onSubmit={save}
        onClose={() => setFormOpen(false)}
        onManageLinks={() => {
          setFormOpen(false);
          setLinksOpen(true);
        }}
      />
      <Modal open={linksOpen} onClose={() => setLinksOpen(false)} title={t("submissionLinksTitle")} description={t("submissionLinksDescription")}>
        <SubmissionLinkManager
          links={links}
          onLinksChange={setLinks}
          onLinkRemoved={(linkId) => {
            setAssignments((list) => list.map((item) => ({ ...item, link_ids: item.link_ids.filter((id) => id !== linkId) })));
            setForm((current) => ({ ...current, link_ids: current.link_ids.filter((id) => id !== linkId) }));
          }}
        />
      </Modal>
    </>
  );

  if (selected) {
    const stateLabel = {
      submitted: t("statusSubmitted"),
      quarantine: t("statusInQuarantine"),
      closed: t("statusClosed"),
      open: t("statusOpen"),
      missed: t("statusNotSubmitted"),
      pending: t("statusPending"),
    };
    const visible = elements.filter((element) => {
      const state = elementState(element);
      return elementFilter === "all" || (elementFilter === "open" ? state === "open" || state === "missed" || state === "pending" : state === elementFilter);
    });
    const summary = summaries[selected.id];
    return (
      <div className="mobile-page mobile-page-list">
        <MobileSubHeader
          title={selected.title}
          subtitle={summary?.total ? `${sourceMeta(selected)} · ${t("countOfTotal", { count: summary.submitted, total: summary.total })}` : sourceMeta(selected)}
          backLabel={t("pageTitle")}
          onBack={() => setSelectedId(null)}
          actions={
            <button type="button" className="mobile-icon-button" aria-label={t("colActions")} onClick={() => setActionsOpen(true)}>
              <MobileIcon name="more" />
            </button>
          }
        />
        <MobileChipRow>
          {(["all", "submitted", "open", "quarantine"] as ElementFilter[]).map((value) => (
            <MobileChip key={value} active={elementFilter === value} onClick={() => setElementFilter(value)}>
              {value === "all" ? t("allAction") : value === "submitted" ? t("statusSubmitted") : value === "open" ? t("statusOpen") : t("scanPending")}
            </MobileChip>
          ))}
        </MobileChipRow>
        {visible.length > 0 ? (
          <div className="mobile-section">
            <div className="mobile-card mobile-list-card">
              {visible.map((element) => {
                const state = elementState(element);
                const person = participantName(element.responsible_participant_id);
                return (
                  <MobileListRow
                    key={element.element_ref}
                    onClick={() => void openElementSheet(element)}
                    leading={person ? <MobileAvatar name={person} size="sm" /> : undefined}
                    label={
                      <span className="mobile-row-stack">
                        <span className="mobile-row-title">{person ? `${element.label} · ${person}` : element.label}</span>
                        <span className="mobile-row-meta">
                          {element.files.length ? t("fileCount", { count: element.files.length }) : t("notSubmittedYet")}
                          {element.window_end ? ` · ${t("deadlineColon")} ${dateParts.dayMonth(element.window_end.slice(0, 10), locale)}` : ""}
                        </span>
                      </span>
                    }
                    trailing={<span className={`mobile-submission-pill mobile-submission-pill-${state}`}>{stateLabel[state]}</span>}
                  />
                );
              })}
            </div>
          </div>
        ) : (
          <MobileEmpty title={t("noElementsFound")} />
        )}
        <div className="mobile-section">
          <button
            type="button"
            className="button-secondary mobile-button-block"
            onClick={() => void download(`/api/submission-assignments/${selected.id}/download-zip`, `${selected.title}.zip`).catch(() => showToast(t("downloadFailed"), "error"))}
          >
            {t("downloadAllZipTitle")}
          </button>
        </div>

        {actionsOpen ? (
          <MobileActionSheet
            title={selected.title}
            onClose={() => setActionsOpen(false)}
            actions={[
              {
                label: t("editAction"),
                onClick: () => {
                  setEditingId(selected.id);
                  setForm(formFromAssignment(selected));
                  setFormOpen(true);
                },
              },
              { label: t("manageLinksAction"), onClick: () => setLinksOpen(true) },
              { label: t("delete"), onClick: () => void remove(selected), danger: true },
            ]}
          />
        ) : null}
        {openElement ? (
          <Modal
            open
            size="sheet"
            title={participantName(openElement.responsible_participant_id) ?? openElement.label}
            description={[openElement.label, openElement.window_end ? `${t("deadlineColon")} ${dateParts.dayMonth(openElement.window_end.slice(0, 10), locale)}` : null].filter(Boolean).join(" · ")}
            onClose={() => setOpenElement(null)}
            className="mobile-sheet mobile-sheet-tall"
            footer={
              <div className="modal-actions mobile-sheet-footer">
                <button type="button" className="button-secondary" onClick={() => void setElementOpen(openElement, openElement.status === "closed")}>
                  {openElement.status === "closed" ? t("reopenAction") : t("closeElementAction")}
                </button>
              </div>
            }
          >
            <div className="mobile-field-block">
              <div className="mobile-eyebrow">{t("filesLabel")}</div>
              <div className="mobile-card mobile-group-card">
                {openElement.files.length === 0 ? <MobileListRow label={t("noFilesPresent")} /> : null}
                {openElement.files.map((file) => (
                  <MobileListRow
                    key={file.id}
                    leading={<FileTypeTile name={file.original_name} />}
                    label={
                      <span className="mobile-row-stack">
                        <span className="mobile-row-title">{file.original_name}</span>
                        <span className="mobile-row-meta">
                          {[formatFileSize(file.file_size_bytes) || null, file.scan_status === "clean" ? t("scanClean") : file.scan_status === "infected" ? t("scanInfected") : file.scan_status === "error" ? t("scanError") : t("scanPending")]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                      </span>
                    }
                    trailing={
                      file.scan_status === "clean" ? (
                        <button type="button" className="mobile-icon-button" aria-label={t("downloadFileTitle")} onClick={() => void download(file.content_url, file.original_name).catch(() => showToast(t("downloadFailed"), "error"))}>
                          <MobileIcon name="chevronDown" />
                        </button>
                      ) : undefined
                    }
                  />
                ))}
              </div>
            </div>
            <div className="mobile-field-block">
              <div className="mobile-eyebrow">{t("logLabel")}</div>
              <div className="mobile-card mobile-group-card">
                {log.length === 0 ? <MobileListRow label={t("noEntriesPresent")} /> : null}
                {log.map((entry) => (
                  <MobileListRow
                    key={entry.id}
                    label={
                      <span className="mobile-row-stack">
                        <span className="mobile-row-title">{logLabels[entry.status] ?? entry.status}</span>
                        <span className="mobile-row-meta">{new Date(entry.created_at).toLocaleString(locale)}{entry.error_message ? ` · ${entry.error_message}` : ""}</span>
                      </span>
                    }
                  />
                ))}
              </div>
            </div>
          </Modal>
        ) : null}
        {shared}
      </div>
    );
  }

  const visible = assignments.filter((assignment) => !search.trim() || assignment.title.toLowerCase().includes(search.trim().toLowerCase()));
  return (
    <div className="mobile-page mobile-page-list">
      <MobileSubHeader
        title={t("pageTitle")}
        subtitle={t("pageIntroEmpty")}
        backLabel={tMobile("tabs.more")}
        onBack={openMore}
        actions={
          <button type="button" className="mobile-icon-button" aria-label={t("submissionLinksTitle")} onClick={() => setLinksOpen(true)}>
            <MobileIcon name="document" />
          </button>
        }
      />
      <div className="mobile-section">
        <p className={clamav === "offline" ? "mobile-clamav mobile-clamav-offline" : "mobile-clamav"}>
          {clamav === "online" ? t("clamavActive") : clamav === "offline" ? t("clamavOfflineHint") : t("clamavChecking")} · {t("linksCount", { count: links.length })}
        </p>
        <SearchInput value={search} onChange={setSearch} placeholder={t("searchAssignmentsPlaceholder")} />
      </div>
      {visible.length > 0 ? (
        <div className="mobile-section">
          <div className="mobile-card mobile-list-card">
            {visible.map((assignment) => {
              const summary = summaries[assignment.id];
              return (
                <MobileListRow
                  key={assignment.id}
                  onClick={() => void openAssignment(assignment)}
                  label={
                    <span className="mobile-row-stack">
                      <span className="mobile-row-title">{assignment.title}</span>
                      <span className="mobile-row-meta">{sourceMeta(assignment)}</span>
                      {summary && summary.total ? (
                        <MobileProgress value={summary.submitted} max={summary.total} label={t("countOfTotal", { count: summary.submitted, total: summary.total })} />
                      ) : null}
                      {summary && (summary.quarantine > 0 || summary.infected > 0) ? (
                        <span className="mobile-row-pills">
                          {summary.quarantine > 0 ? <span className="mobile-status-pill">{t("quarantineCount", { count: summary.quarantine })}</span> : null}
                          {summary.infected > 0 ? <span className="mobile-overdue-pill">{t("infectedCount", { count: summary.infected })}</span> : null}
                        </span>
                      ) : null}
                    </span>
                  }
                />
              );
            })}
          </div>
        </div>
      ) : (
        <MobileEmpty title={assignments.length ? t("noMatches") : t("noAssignmentsSetUp")} hint={assignments.length ? undefined : t("noAssignmentsDescription")} />
      )}
      <MobileFab
        label={tMobile("submissions.fab")}
        onClick={() => {
          setEditingId(null);
          setForm({ ...initialForm, link_ids: links.filter((link) => link.is_default).map((link) => link.id) });
          setFormOpen(true);
        }}
      />
      {shared}
    </div>
  );
}
