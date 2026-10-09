"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { ActionIcon } from "@/components/ui/action-icons";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import {
  FormState,
  SubmissionAssignmentFormModal,
  cycleOffsetLabel,
  formFromAssignment,
  initialForm,
  assignmentPayload,
} from "@/components/submission-assignments/submission-assignment-form";
import { SubmissionLinkManager } from "@/components/submission-assignments/submission-link-manager";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import {
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

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

function logStatusLabel(t: TFunc): Record<string, string> {
  return {
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
}

const LOG_STATUS_VARIANT: Record<string, BadgeVariant> = {
  upload_received: "neutral",
  quarantined: "warning",
  moved_to_storage: "success",
  submitted: "success",
  captcha_failed: "warning",
  validation_failed: "warning",
  element_closed: "warning",
  upload_error: "danger",
  scan_clean: "success",
  scan_pending: "warning",
  scan_infected: "danger",
  rescan_clean: "success",
  rescan_infected: "danger",
  rescan_pending: "warning",
};

function scanStatusLabel(t: TFunc): Record<string, string> {
  return {
    clean: t("scanClean"),
    pending: t("scanPending"),
    error: t("scanError"),
    infected: t("scanInfected"),
  };
}

const SCAN_STATUS_VARIANT: Record<string, BadgeVariant> = {
  clean: "success",
  pending: "warning",
  error: "danger",
  infected: "danger",
};

type Props = {
  initialAssignments: SubmissionAssignment[];
  initialLinks: SubmissionLink[];
  availableLists: StructuredListDefinition[];
  availableEvents: EventSummary[];
  availableParticipants: ParticipantSummary[];
  availableCycleConfigs: CycleConfigSummary[];
  tenantName?: string | null;
};

function statusLabel(element: SubmissionElementStatusEntry, t: TFunc): string {
  if (element.status === "closed") return t("statusClosed");
  if (element.status === "submitted") {
    if (element.files.some((f) => f.scan_status === "error")) return t("scanError");
    if (element.files.some((f) => f.scan_status === "pending")) return t("statusInQuarantine");
    return t("statusSubmitted");
  }
  const now = new Date();
  const end = element.window_end ? new Date(element.window_end) : null;
  const start = element.window_start ? new Date(element.window_start) : null;
  if (end && now > end) return t("statusNotSubmitted");
  if (start && now < start) return t("statusPending");
  return t("statusOpen");
}

function statusVariant(element: SubmissionElementStatusEntry): BadgeVariant | null {
  if (element.status === "closed") return "neutral";
  if (element.status === "submitted") {
    if (element.files.some((f) => f.scan_status === "error")) return "danger";
    if (element.files.some((f) => f.scan_status === "pending")) return "warning";
    return "success";
  }
  return null;
}

function SummaryBar({ summary, size = "row" }: { summary: AssignmentSummary | undefined; size?: "row" | "detail" }) {
  const t = useTranslations("submissionAssignments");
  const isDetail = size === "detail";
  const wrapClass = `subm-summary ${isDetail ? "subm-summary-detail" : "subm-summary-list"}`;

  if (!summary) {
    return (
      <div className={wrapClass}>
        <div className="subm-summary-track" />
      </div>
    );
  }

  const { submitted, quarantine, infected, total } = summary;
  const clean = Math.max(0, submitted);
  const known = total !== null && total > 0;
  const sum = clean + quarantine + infected;
  const denom = known ? (total as number) : sum;

  if (denom === 0) {
    return (
      <div className={wrapClass}>
        <div className="subm-summary-track" />
        <span className="subm-summary-caption">{t("noSubmissionsYet")}</span>
      </div>
    );
  }

  const cleanPct = Math.min(100, (clean / denom) * 100);
  const qPct = Math.min(100 - cleanPct, (quarantine / denom) * 100);
  const infPct = Math.min(100 - cleanPct - qPct, (infected / denom) * 100);
  const missingPct = Math.max(0, 100 - cleanPct - qPct - infPct);

  const countLabel = known ? t("countOfTotal", { count: sum, total }) : `${sum}`;
  const extraParts = [
    quarantine > 0 ? t("quarantineCount", { count: quarantine }) : null,
    infected > 0 ? t("infectedCount", { count: infected }) : null,
  ].filter((v): v is string => Boolean(v));

  const track = (
    <div className="subm-summary-track">
      {cleanPct > 0 && <div className="subm-summary-segment subm-summary-segment-clean" style={{ width: `${cleanPct}%` }} />}
      {qPct > 0 && <div className="subm-summary-segment subm-summary-segment-quarantine" style={{ width: `${qPct}%` }} />}
      {infPct > 0 && <div className="subm-summary-segment subm-summary-segment-infected" style={{ width: `${infPct}%` }} />}
      {!isDetail && missingPct > 0 && <div className="subm-summary-segment" style={{ width: `${missingPct}%` }} />}
    </div>
  );

  if (isDetail) {
    return (
      <div className={wrapClass}>
        <div className="subm-summary-detail-row">
          {track}
          <span className="subm-summary-detail-count">{countLabel}</span>
        </div>
        {extraParts.length > 0 ? <span className="subm-summary-caption">{extraParts.join(" · ")}</span> : null}
      </div>
    );
  }

  return (
    <div className={wrapClass}>
      {track}
      <span className="subm-summary-caption">
        {t("submittedCount", { label: countLabel })}{extraParts.length > 0 ? ` · ${extraParts.join(" · ")}` : ""}
      </span>
    </div>
  );
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function monthAbbrs(t: TFunc): string[] {
  return [
    t("monthJan"), t("monthFeb"), t("monthMar"), t("monthApr"), t("monthMay"), t("monthJun"),
    t("monthJul"), t("monthAug"), t("monthSep"), t("monthOct"), t("monthNov"), t("monthDec"),
  ];
}

function formatDateShort(iso: string, t: TFunc): string {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return `${String(d.getDate()).padStart(2, "0")}. ${monthAbbrs(t)[d.getMonth()]} ${d.getFullYear()}`;
}

function relativeTime(iso: string, t: TFunc): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const minute = 60_000;
  const hour = 3_600_000;
  const day = 86_400_000;
  if (diffMs < minute) return t("justNow");
  if (diffMs < hour) {
    const m = Math.max(1, Math.round(diffMs / minute));
    return t("minutesAgo", { count: m });
  }
  if (diffMs < day) {
    const h = Math.round(diffMs / hour);
    return t("hoursAgo", { count: h });
  }
  const d = Math.round(diffMs / day);
  if (d <= 1) return t("yesterday");
  return t("daysAgo", { count: d });
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" width="14" height="14">
      <path d="M12 3v12m0 0 4.5-4.5M12 15l-4.5-4.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" width="14" height="14">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
      <path d="M14 3v5h5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
    </svg>
  );
}

function VerifiedIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16">
      <path
        d="M12 2.5l2.2 1.2 2.5-.4 1.2 2.2 2.2 1.2-.4 2.5L21 12l-1.3 2.2.4 2.5-2.2 1.2-1.2 2.2-2.5-.4L12 21.5l-2.2-1.2-2.5.4-1.2-2.2-2.2-1.2.4-2.5L3 12l1.3-2.2-.4-2.5 2.2-1.2 1.2-2.2 2.5.4z"
        fill="currentColor"
        opacity="0.16"
      />
      <path d="M8.3 12.3l2.4 2.4L16 9.3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function SubmissionAssignmentManager({ initialAssignments, initialLinks, availableLists, availableEvents, availableParticipants, availableCycleConfigs, tenantName = null }: Props) {
  const t = useTranslations("submissionAssignments");
  const showToast = useToast();
  const confirm = useConfirm();
  const [assignments, setAssignments] = useState(initialAssignments);
  const [links, setLinks] = useState(initialLinks);
  const [linksModalOpen, setLinksModalOpen] = useState(false);
  // "Abgabe-Links verwalten" im Formular: das Formular wird für die Links geschlossen (Entwurf bleibt
  // im State) und danach wieder geöffnet – kein zweites Modal im Modal.
  const [linksReturnToForm, setLinksReturnToForm] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(initialForm);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [zipLoading, setZipLoading] = useState(false);
  const [elements, setElements] = useState<SubmissionElementStatusEntry[]>([]);
  const [elementsLoading, setElementsLoading] = useState(false);
  const [clamavStatus, setClamavStatus] = useState<"online" | "offline" | "unknown">("unknown");
  const [summaries, setSummaries] = useState<Record<string, AssignmentSummary>>({});
  const rescanTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [elementModal, setElementModal] = useState<SubmissionElementStatusEntry | null>(null);
  const [logEntries, setLogEntries] = useState<SubmissionUploadLogEntry[]>([]);
  const [logLoading, setLogLoading] = useState(false);
  const [search, setSearch] = useState("");

  const availableTags = Array.from(
    new Set(availableEvents.map((e) => e.tag).filter((t): t is string => Boolean(t)))
  ).sort();

  // Load ClamAV status and all assignment summaries on mount
  useEffect(() => {
    void browserApiFetch<{ status: string }>("/api/clamav/status").then(
      (d) => setClamavStatus(d.status === "online" ? "online" : "offline"),
      () => setClamavStatus("offline"),
    );
    void Promise.all(
      initialAssignments.map((a) =>
        browserApiFetch<AssignmentSummary>(`/api/submission-assignments/${a.id}/summary`)
          .then((s) => setSummaries((prev) => ({ ...prev, [a.id]: s })))
          .catch(() => {})
      )
    );
  }, []);

  const filteredAssignments = search.trim()
    ? assignments.filter((a) => a.title.toLowerCase().includes(search.toLowerCase()))
    : assignments;

  function openCreate() {
    setEditingId(null);
    // Default link(s) are preselected for a new Abgabe.
    setForm({ ...initialForm, link_ids: links.filter((link) => link.is_default).map((link) => link.id) });
    setModalOpen(true);
  }

  function openLinksFromForm() {
    setModalOpen(false);
    setLinksReturnToForm(true);
    setLinksModalOpen(true);
  }

  function closeLinksModal() {
    setLinksModalOpen(false);
    if (linksReturnToForm) {
      setLinksReturnToForm(false);
      setModalOpen(true);
    }
  }

  // A deleted link disappears from every Abgabe on the server (and from the edit form, if open).
  function handleLinkRemoved(linkId: string) {
    setAssignments((current) => current.map((a) => ({ ...a, link_ids: a.link_ids.filter((id) => id !== linkId) })));
    setForm((c) => ({ ...c, link_ids: c.link_ids.filter((id) => id !== linkId) }));
  }

  function openEdit(assignment: SubmissionAssignment) {
    setEditingId(assignment.id);
    setForm(formFromAssignment(assignment));
    setModalOpen(true);
  }

  function clearRescanTimer() {
    if (rescanTimerRef.current !== null) {
      clearTimeout(rescanTimerRef.current);
      rescanTimerRef.current = null;
    }
  }

  async function refreshElements(assignmentId: string): Promise<SubmissionElementStatusEntry[]> {
    const data = await browserApiFetch<SubmissionElementStatusEntry[]>(
      `/api/submission-assignments/${assignmentId}/elements`
    );
    setElements(data);
    void browserApiFetch<{ status: string }>("/api/clamav/status").then(
      (d) => setClamavStatus(d.status === "online" ? "online" : "offline"),
      () => setClamavStatus("offline"),
    );
    // Refresh summary for this assignment
    void browserApiFetch<AssignmentSummary>(`/api/submission-assignments/${assignmentId}/summary`)
      .then((s) => setSummaries((prev) => ({ ...prev, [assignmentId]: s })))
      .catch(() => {});
    return data;
  }

  async function scheduleAutoRescan(assignmentId: string, delayMs = 5000) {
    clearRescanTimer();
    rescanTimerRef.current = setTimeout(async () => {
      try {
        const result = await browserApiFetch<{ scanned: number; clean: number; infected: number; still_pending: number }>(
          `/api/submission-assignments/${assignmentId}/rescan-pending`,
          { method: "POST" }
        );
        const data = await refreshElements(assignmentId);
        const stillHasPending = data.some((el) => el.files.some((f) => f.scan_status === "pending"));
        if (stillHasPending) {
          scheduleAutoRescan(assignmentId, 30000);
        }
        if (result.clean > 0 || result.infected > 0) {
          showToast(
            result.infected > 0
              ? t("virusScanInfectedFound", { count: result.infected })
              : t("virusScanClean", { count: result.clean }),
            result.infected > 0 ? "error" : "success"
          );
        }
      } catch {
        scheduleAutoRescan(assignmentId, 30000);
      }
    }, delayMs);
  }

  async function loadElements(assignmentId: string) {
    clearRescanTimer();
    setSelectedId(assignmentId);
    setElementsLoading(true);
    try {
      const data = await refreshElements(assignmentId);
      const hasPending = data.some((el) => el.files.some((f) => f.scan_status === "pending"));
      if (hasPending) {
        scheduleAutoRescan(assignmentId, 5000);
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("elementsLoadFailed"), "error");
    } finally {
      setElementsLoading(false);
    }
  }

  useEffect(() => {
    return () => clearRescanTimer();
  }, []);

  async function submit() {
    const payload = assignmentPayload(form);

    try {
      const saved = editingId
        ? await browserApiFetch<SubmissionAssignment>(`/api/submission-assignments/${editingId}`, {
            method: "PATCH",
            body: JSON.stringify(payload),
          })
        : await browserApiFetch<SubmissionAssignment>("/api/submission-assignments", {
            method: "POST",
            body: JSON.stringify(payload),
          });
      setAssignments((current) =>
        editingId ? current.map((item) => (item.id === saved.id ? saved : item)) : [saved, ...current]
      );
      // Initialise summary for new assignment
      if (!editingId) {
        setSummaries((prev) => ({ ...prev, [saved.id]: { submitted: 0, quarantine: 0, infected: 0, total: null } }));
      }
      setModalOpen(false);
      showToast(editingId ? t("assignmentSavedToast") : t("assignmentCreatedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("assignmentSaveFailed"), "error");
    }
  }

  async function deleteAssignment(id: string) {
    const ok = await confirm({
      message: t("deleteAssignmentConfirm"),
      tone: "danger",
    });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/submission-assignments/${id}`, { method: "DELETE" });
      setAssignments((current) => current.filter((item) => item.id !== id));
      setSummaries((prev) => { const n = { ...prev }; delete n[id]; return n; });
      if (selectedId === id) {
        setSelectedId(null);
        setElements([]);
      }
      showToast(t("assignmentDeletedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("assignmentDeleteFailed"), "error");
    }
  }

  async function downloadZip(assignmentId: string) {
    setZipLoading(true);
    try {
      const { browserApiBaseUrl } = await import("@/lib/api/client");
      const res = await fetch(`${browserApiBaseUrl}/api/submission-assignments/${assignmentId}/download-zip`, {
        credentials: "include",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const assignment = assignments.find((x) => x.id === assignmentId);
      a.href = url;
      a.download = `${assignment?.title ?? "abgaben"}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("downloadFailed"), "error");
    } finally {
      setZipLoading(false);
    }
  }

  async function downloadFile(url: string, filename: string) {
    try {
      const { browserApiBaseUrl } = await import("@/lib/api/client");
      const absoluteUrl = url.startsWith("http") ? url : `${browserApiBaseUrl}${url}`;
      const res = await fetch(absoluteUrl, { credentials: "include" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(blobUrl);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("downloadFailed"), "error");
    }
  }

  async function openElementModal(assignmentId: string, element: SubmissionElementStatusEntry) {
    setElementModal(element);
    setLogEntries([]);
    setLogLoading(true);
    try {
      const data = await browserApiFetch<SubmissionUploadLogEntry[]>(
        `/api/submission-assignments/${assignmentId}/upload-log?element_ref=${encodeURIComponent(element.element_ref)}`
      );
      setLogEntries(data);
    } catch {
      showToast(t("logLoadFailed"), "error");
    } finally {
      setLogLoading(false);
    }
  }

  async function reopenElement(assignmentId: string, elementRef: string) {
    try {
      const updated = await browserApiFetch<SubmissionElementStatusEntry>(
        `/api/submission-assignments/${assignmentId}/elements/${elementRef}/reopen`,
        { method: "POST" }
      );
      setElements((current) => current.map((el) => (el.element_ref === elementRef ? updated : el)));
      setElementModal((current) => (current?.element_ref === elementRef ? updated : current));
      showToast(t("elementReopenedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("elementReopenFailed"), "error");
    }
  }

  async function closeElement(assignmentId: string, elementRef: string) {
    try {
      const updated = await browserApiFetch<SubmissionElementStatusEntry>(
        `/api/submission-assignments/${assignmentId}/elements/${elementRef}/close`,
        { method: "POST" }
      );
      setElements((current) => current.map((el) => (el.element_ref === elementRef ? updated : el)));
      setElementModal((current) => (current?.element_ref === elementRef ? updated : current));
      showToast(t("elementClosedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("elementCloseFailed"), "error");
    }
  }

  const selectedAssignment = assignments.find((a) => a.id === selectedId);
  const hasPendingFiles = elements.some((el) => el.files.some((f) => f.scan_status === "pending"));

  function metaLine(assignment: SubmissionAssignment): string {
    if (assignment.source_type === "events") {
      const cycleConfig = availableCycleConfigs.find((c) => c.id === assignment.cycle_config_id);
      const cycles = cycleConfig
        ? ` (${cycleConfig.name}: ${[...assignment.cycle_offsets].sort((a, b) => b - a).map((offset) => cycleOffsetLabel(offset, t)).join(", ")})`
        : "";
      const source = (assignment.tag_filter ? t("sourceEventTagged", { tag: assignment.tag_filter }) : t("sourceEvents")) + cycles;
      const before = assignment.offset_days_before;
      const after = assignment.offset_days_after;
      const windowParts = [
        before !== null ? t("fromDaysBefore", { count: before }) : null,
        after !== null ? t("untilDaysAfter", { count: after }) : null,
      ].filter((v): v is string => Boolean(v));
      const window = windowParts.length > 0 ? windowParts.join(", ") : t("noWindowOpenUntilClosed");
      return t("sourceSummary", { source, window });
    }
    if (assignment.source_type === "manual") {
      const deadline = assignment.deadline ? t("deadlineNamed", { date: formatDateShort(assignment.deadline, t) }) : t("noDeadlineOpenUntilClosed");
      return t("sourceSummaryManual", { deadline });
    }
    const list = availableLists.find((l) => l.id === assignment.list_definition_id);
    const source = list ? t("sourceListNamed", { name: list.name }) : t("sourceList");
    const deadline = assignment.deadline ? t("deadlineNamed", { date: formatDateShort(assignment.deadline, t) }) : t("noDeadlineOpenUntilClosed");
    return t("sourceSummary", { source, window: deadline });
  }

  const hasNoAssignments = assignments.length === 0;

  return (
    <div className="grid subm-root">
      {/* Header — always visible, including ClamAV status */}
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("pageTitle")}</h1>
          <p className="muted">{hasNoAssignments ? t("pageIntroEmpty") : t("pageIntro")}</p>
        </div>
        <div className="table-toolbar-actions">
          <span
            className={`subm-clamav subm-clamav-${clamavStatus}`}
            title={clamavStatus === "offline" ? t("clamavOfflineHint") : undefined}
          >
            <span className="subm-clamav-dot" />
            {clamavStatus === "online" ? t("clamavActive") : clamavStatus === "offline" ? t("clamavOffline") : t("clamavChecking")}
          </span>
          <button type="button" className="button-ghost" onClick={() => setLinksModalOpen(true)}>
            {t("linksCount", { count: links.length })}
          </button>
          {hasNoAssignments ? null : (
            <button type="button" className="button-primary subm-new-button" onClick={openCreate}>
              {t("newAssignmentPlus")}
            </button>
          )}
        </div>
      </div>

      {hasNoAssignments ? (
        <EmptyState
          title={t("noAssignmentsSetUp")}
          description={t("noAssignmentsDescription")}
          actions={
            <button type="button" className="button-primary" onClick={openCreate}>
              {t("newAssignmentPlus")}
            </button>
          }
          hint={t("emptyStateHint")}
        />
      ) : (
      <>
      <div className="list-filter-row">
        <div />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder={t("searchAssignmentsPlaceholder")} />
        </div>
      </div>

      <DataTable
        className="data-table-lg"
        columns={[t("colTitle"), t("colSourcePeriod"), t("colProgress"), t("colActions")]}
        emptyMessage={t("noMatches")}
      >
          {filteredAssignments.map((assignment) => (
            <tr
              key={assignment.id}
              className="table-row-clickable"
              onClick={() => void loadElements(assignment.id)}
            >
              <td className="table-cell-wrap">
                <strong>{assignment.title}</strong>
              </td>
              <td className="table-cell-wrap">
                <span className="muted">{metaLine(assignment)}</span>
              </td>
              <td>
                <SummaryBar summary={summaries[assignment.id]} />
              </td>
              <td>
                <div className="table-actions table-actions-start">
                  <button
                    type="button"
                    className="subm-sidebar-icon-button"
                    onClick={(e) => { e.stopPropagation(); openEdit(assignment); }}
                    aria-label={t("editAction")}
                    title={t("editAction")}
                  >
                    <ActionIcon name="edit" />
                  </button>
                  <button
                    type="button"
                    className="subm-sidebar-icon-button subm-sidebar-icon-button-danger"
                    onClick={(e) => { e.stopPropagation(); void deleteAssignment(assignment.id); }}
                    aria-label={t("delete")}
                    title={t("delete")}
                  >
                    <ActionIcon name="delete" />
                  </button>
                </div>
              </td>
            </tr>
          ))}
      </DataTable>
      </>
      )}

      {/* Assignment detail popup — participants + progress */}
      <Modal
        open={selectedId !== null}
        onClose={() => setSelectedId(null)}
        title={selectedAssignment?.title ?? ""}
        description={selectedAssignment ? metaLine(selectedAssignment) : undefined}
        size="wide"
      >
        {selectedId !== null ? (
          <div className="grid subm-detail">
            <SummaryBar summary={summaries[selectedId]} size="detail" />

            {hasPendingFiles && (
              <Badge variant="warning" className="subm-pulse">
                {t("filesInQuarantine")}
              </Badge>
            )}

            <div className="subm-modal-section-title">{selectedAssignment?.source_type === "manual" ? t("assignmentLabel") : t("participantsLabel")}</div>

            {elementsLoading ? (
              <div className="subm-skeleton-box">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="subm-skeleton-row" style={{ animationDelay: `${i * 90}ms` }} />
                ))}
              </div>
            ) : elements.length === 0 ? (
              <p className="muted">{t("noElementsFound")}</p>
            ) : (
              <div className="subm-participant-list">
                {elements.map((element, rowIndex) => {
                  const responsibleName = element.responsible_participant_id
                    ? (availableParticipants.find((p) => p.id === element.responsible_participant_id)?.display_name ?? t("unknownParticipant"))
                    : null;
                  const displayName = responsibleName ?? element.label;
                  const hasFiles = element.files.length > 0;
                  const variant = statusVariant(element);
                  const label = statusLabel(element, t);
                  const meta = hasFiles
                    ? `${t("fileCount", { count: element.files.length })}${element.submitted_at ? ` · ${relativeTime(element.submitted_at, t)}` : ""}`
                    : t("notSubmittedYet");
                  return (
                    <div
                      key={element.element_ref}
                      className="subm-participant-row"
                      style={{ animationDelay: `${Math.min(rowIndex, 14) * 25}ms` }}
                      onClick={() => void openElementModal(selectedId, element)}
                    >
                      <span className="subm-avatar subm-avatar-lg">{initials(displayName)}</span>
                      <div className="subm-participant-info">
                        <div className="subm-participant-name">{displayName}</div>
                        <div className="subm-participant-meta">{meta}</div>
                      </div>
                      <div className="subm-participant-status">
                        <Badge variant={variant ?? "neutral"}>
                          {hasFiles ? <DownloadIcon /> : null} {label}
                        </Badge>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="subm-detail-footer">
              <button
                type="button"
                className="button-ghost button-secondary"
                onClick={() => void downloadZip(selectedId)}
                disabled={zipLoading}
                title={t("downloadAllZipTitle")}
              >
                <DownloadIcon /> {zipLoading ? "…" : t("allFilesZip")}
              </button>
              <button type="button" className="button-secondary" onClick={() => setSelectedId(null)}>
                {t("close")}
              </button>
            </div>
          </div>
        ) : null}
      </Modal>

      {/* Element detail popup — files + log combined */}
      <Modal
        open={elementModal !== null}
        onClose={() => setElementModal(null)}
        title={elementModal?.label ?? t("elementFallback")}
        size="wide"
      >
        {elementModal ? (
          <div className="grid subm-element-modal">
            <div className="status-row">
              {statusVariant(elementModal) ? (
                <Badge variant={statusVariant(elementModal)!}>{statusLabel(elementModal, t)}</Badge>
              ) : (
                <Badge variant="neutral">{statusLabel(elementModal, t)}</Badge>
              )}
              {elementModal.window_start && elementModal.window_end ? (
                <span className="subm-modal-meta">{elementModal.window_start} – {elementModal.window_end}</span>
              ) : elementModal.window_end ? (
                <span className="subm-modal-meta">{t("deadlineColon")} {elementModal.window_end}</span>
              ) : null}
              {elementModal.responsible_participant_id ? (() => {
                const name = availableParticipants.find((p) => p.id === elementModal.responsible_participant_id)?.display_name
                  ?? t("unknownParticipant");
                return (
                  <span className="subm-responsible">
                    <span className="subm-avatar">{initials(name)}</span>
                    {name}
                  </span>
                );
              })() : null}
            </div>

            <div className="subm-modal-section">
              <div className="subm-modal-section-title">{t("filesLabel")}</div>
              {elementModal.files.length === 0 ? (
                <p className="muted">{t("noFilesPresent")}</p>
              ) : (
                <div className="subm-file-list subm-file-list-modal">
                  {elementModal.files.map((file) => (
                    <div key={file.id} className="subm-file-row">
                      <span className="subm-file-icon"><FileIcon /></span>
                      {file.scan_status === "clean" ? (
                        <a href={file.content_url} target="_blank" rel="noreferrer" className="subm-file-link">
                          {file.original_name}
                        </a>
                      ) : (
                        <span className="subm-file-name-muted">{file.original_name}</span>
                      )}
                      {file.scan_status === "clean" ? (
                        <>
                          <span className="subm-verified" title={t("verified")}>
                            <VerifiedIcon />
                          </span>
                          <button
                            type="button"
                            className="subm-file-download-button"
                            title={t("downloadFileTitle")}
                            onClick={() => void downloadFile(file.content_url, file.original_name)}
                          >
                            <DownloadIcon />
                          </button>
                        </>
                      ) : (
                        <Badge variant={SCAN_STATUS_VARIANT[file.scan_status] ?? "neutral"}>
                          {scanStatusLabel(t)[file.scan_status] ?? file.scan_status}
                        </Badge>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="table-toolbar-actions">
              {elementModal.status === "closed" ? (
                <button
                  type="button"
                  className="button-ghost button-secondary subm-reopen-button"
                  onClick={() => selectedId && void reopenElement(selectedId, elementModal.element_ref)}
                >
                  {t("reopenAction")}
                </button>
              ) : (
                <button
                  type="button"
                  className="button-ghost button-secondary subm-close-button"
                  onClick={() => selectedId && void closeElement(selectedId, elementModal.element_ref)}
                >
                  {t("closeElementAction")}
                </button>
              )}
            </div>

            <div className="subm-modal-section">
              <div className="subm-modal-section-title">{t("logLabel")}</div>
              {logLoading ? (
                <p className="muted">{t("loadingEllipsis")}</p>
              ) : logEntries.length === 0 ? (
                <p className="muted">{t("noEntriesPresent")}</p>
              ) : (
                <div className="subm-log-list">
                  {logEntries.map((entry) => {
                    const variant = LOG_STATUS_VARIANT[entry.status] ?? "neutral";
                    const tone = variant === "danger" ? "error" : variant;
                    return (
                      <div key={entry.id} className={`subm-log-entry subm-log-entry-${tone}`}>
                        <span className="subm-log-dot" />
                        <div className="subm-log-body">
                          <div className="subm-log-header">
                            <Badge variant={variant}>{logStatusLabel(t)[entry.status] ?? entry.status}</Badge>
                            <span className="subm-log-time">{new Date(entry.created_at).toLocaleString("de-CH")}</span>
                          </div>
                          {entry.error_message ? <div className="subm-log-detail">{entry.error_message}</div> : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        ) : null}
      </Modal>

      {/* Links: Zugang zur öffentlichen Abgabebox */}
      <Modal
        open={linksModalOpen}
        onClose={closeLinksModal}
        title={t("submissionLinksTitle")}
        description={t("submissionLinksDescription")}
      >
        <SubmissionLinkManager links={links} onLinksChange={setLinks} onLinkRemoved={handleLinkRemoved} />
      </Modal>

      {/* Create/Edit Modal */}
      <SubmissionAssignmentFormModal
        open={modalOpen}
        editing={editingId !== null}
        tenantName={tenantName}
        form={form}
        setForm={setForm}
        links={links}
        availableLists={availableLists}
        availableTags={availableTags}
        availableCycleConfigs={availableCycleConfigs}
        onSubmit={submit}
        onClose={() => setModalOpen(false)}
        onManageLinks={openLinksFromForm}
      />
    </div>
  );
}
