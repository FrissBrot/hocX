"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { StatusBanner } from "@/components/ui/status-banner";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { ActionIcon } from "@/components/ui/action-icons";
import { EmptyState } from "@/components/ui/empty-state";
import { DocsLink } from "@/components/ui/help-popover";
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
import { AssignmentLinkField, SubmissionCreatedModal } from "@/components/submission-assignments/submission-share-link";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate, formatDateTime } from "@/lib/utils/format";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { useDeleteWithFiles } from "@/components/ui/delete-with-files-modal";
import {
  AssignmentSummary,
  CycleConfigSummary,
  EventSummary,
  ParticipantSummary,
  StructuredListDefinition,
  SubmissionAssignment,
  SubmissionElementStatusEntry,
  SubmissionFile,
  SubmissionLink,
  SubmissionReviewerCandidate,
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
  /** Öffnet diese Abgabe beim Laden (``?assignment=`` aus der Dateiübersicht). */
  initialSelectedId?: string | null;
  /** Mit ``initialSelectedId``: gleich im Assistenten bearbeiten (``&edit=1``, «Anpassen» nach «Als Abgabe einsammeln») */
  initialEdit?: boolean;
  /** Wählbare Prüfer (Konten mit Login, nur mit submissions.manage geladen) */
  availableReviewers?: SubmissionReviewerCandidate[];
  /** submissions.manage: Aufträge, Links, Dateien verwalten. Ohne: nur lesen (Prüfer, Phase 4) */
  canManage?: boolean;
  /** submissions.review: Elemente schliessen und wieder öffnen */
  canReview?: boolean;
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

// Jeder Zustand hat eine eigene Farbe: grün = abgegeben, gelb = in Prüfung, blau = läuft,
// grau = noch nicht gestartet oder ohne Abgabe geschlossen, rot = Frist vorbei ohne Abgabe bzw.
// Scanfehler.
function statusVariant(element: SubmissionElementStatusEntry): BadgeVariant {
  if (element.files.some((f) => f.scan_status === "error")) return "danger";
  if (element.files.some((f) => f.scan_status === "pending")) return "warning";
  if (element.status === "submitted") return "success";
  if (element.status === "closed") return element.files.length ? "success" : "neutral";
  const now = new Date();
  const end = element.window_end ? new Date(element.window_end) : null;
  const start = element.window_start ? new Date(element.window_start) : null;
  if (end && now > end) return "danger";
  if (start && now < start) return "neutral";
  return "info";
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

  const { submitted: clean, closed, quarantine, infected, total } = summary;
  const known = total > 0;
  // Abgegeben = geprüft, im Scan oder von Hand geschlossen; infizierte zählen nicht
  const sum = clean + closed + quarantine;
  const denom = known ? total : sum + infected;

  if (denom === 0) {
    return (
      <div className={wrapClass}>
        <div className="subm-summary-track" />
        <span className="subm-summary-caption">{t("noSubmissionsYet")}</span>
      </div>
    );
  }

  const cleanPct = Math.min(100, (clean / denom) * 100);
  const closedPct = Math.min(100 - cleanPct, (closed / denom) * 100);
  const qPct = Math.min(100 - cleanPct - closedPct, (quarantine / denom) * 100);
  const infPct = Math.min(100 - cleanPct - closedPct - qPct, (infected / denom) * 100);
  const missingPct = Math.max(0, 100 - cleanPct - closedPct - qPct - infPct);

  const countLabel = known ? t("countOfTotal", { count: sum, total }) : `${sum}`;
  const extraParts = [
    closed > 0 ? t("closedCount", { count: closed }) : null,
    quarantine > 0 ? t("quarantineCount", { count: quarantine }) : null,
    infected > 0 ? t("infectedCount", { count: infected }) : null,
  ].filter((v): v is string => Boolean(v));

  const track = (
    <div className="subm-summary-track">
      {cleanPct > 0 && <div className="subm-summary-segment subm-summary-segment-clean" style={{ width: `${cleanPct}%` }} />}
      {closedPct > 0 && <div className="subm-summary-segment subm-summary-segment-closed" style={{ width: `${closedPct}%` }} />}
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
        {t(closed > 0 ? "doneCount" : "submittedCount", { label: countLabel })}{extraParts.length > 0 ? ` · ${extraParts.join(" · ")}` : ""}
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

export function SubmissionAssignmentManager({ initialAssignments, initialLinks, availableLists, availableEvents, availableParticipants, availableCycleConfigs, tenantName = null, initialSelectedId = null, initialEdit = false, availableReviewers = [], canManage = true, canReview = true }: Props) {
  const t = useTranslations("submissionAssignments");
  const locale = useLocale();
  const tHelp = useTranslations("common.help");
  const showToast = useToast();
  const confirm = useConfirm();
  const { requestDelete, modal: deleteModal } = useDeleteWithFiles();
  // Alle Verantwortlichen eines Elements (mehrere = gemeinsam), leer = niemand
  const responsibleNames = (element: SubmissionElementStatusEntry) => {
    const ids = element.responsible_participant_ids?.length ? element.responsible_participant_ids : element.responsible_participant_id ? [element.responsible_participant_id] : [];
    return ids.map((id) => availableParticipants.find((p) => p.id === id)?.display_name ?? t("unknownParticipant")).join(", ");
  };
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
  const [elementFilter, setElementFilter] = useState<"all" | "done" | "pending">("all");
  const [logEntries, setLogEntries] = useState<SubmissionUploadLogEntry[]>([]);
  const [logLoading, setLogLoading] = useState(false);
  const [search, setSearch] = useState("");
  // Reiter «Offen» / «Abgeschlossen» (completed_at, docs/SUBMISSION_OWNER_ACCESS.md Teil 2)
  const [completion, setCompletion] = useState<"open" | "completed">("open");
  const [createdAssignment, setCreatedAssignment] = useState<SubmissionAssignment | null>(null);

  const availableTags = Array.from(
    new Set(availableEvents.map((e) => e.tag).filter((t): t is string => Boolean(t)))
  ).sort();

  // Load ClamAV status and all assignment summaries on mount
  useEffect(() => {
    void browserApiFetch<{ status: string }>("/api/clamav/status").then(
      (d) => setClamavStatus(d.status === "online" ? "online" : "offline"),
      () => setClamavStatus("offline"),
    );
    // Fortschritt aller Abgaben in einer Anfrage (statt einer je Abgabe)
    void browserApiFetch<Record<string, AssignmentSummary>>("/api/submission-assignments/summaries")
      .then(setSummaries)
      .catch(() => {});
  }, []);

  const completedCount = assignments.filter((a) => a.completed_at).length;
  const filteredAssignments = assignments
    .filter((a) => (completion === "completed" ? Boolean(a.completed_at) : !a.completed_at))
    .filter((a) => !search.trim() || a.title.toLowerCase().includes(search.toLowerCase()));

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
    // «Abgeschlossen» kann sich nach Schliessen/Wiederöffnen ändern
    void browserApiFetch<SubmissionAssignment[]>("/api/submission-assignments")
      .then((fresh) => {
        const completedById = new Map(fresh.map((item) => [item.id, item.completed_at ?? null]));
        setAssignments((current) => current.map((item) => (completedById.has(item.id) ? { ...item, completed_at: completedById.get(item.id) } : item)));
      })
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
    setElementModal(null);
    setElementFilter("all");
    setElementsLoading(true);
    try {
      const data = await refreshElements(assignmentId);
      const hasPending = data.some((el) => el.files.some((f) => f.scan_status === "pending"));
      // Nachscannen ist eine Verwaltungsaktion (POST …/rescan-pending verlangt submissions.manage)
      if (hasPending && canManage) {
        scheduleAutoRescan(assignmentId, 5000);
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("elementsLoadFailed"), "error");
    } finally {
      setElementsLoading(false);
    }
  }

  // Direkt geöffnete Abgabe (?assignment=), nur beim ersten Laden
  useEffect(() => {
    const initial = initialSelectedId ? initialAssignments.find((assignment) => assignment.id === initialSelectedId) : undefined;
    if (initial) {
      void loadElements(initial.id);
      if (initialEdit && canManage) openEdit(initial);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      void browserApiFetch<AssignmentSummary>(`/api/submission-assignments/${saved.id}/summary`)
        .then((summary) => setSummaries((prev) => ({ ...prev, [saved.id]: summary })))
        .catch(() => {});
      setModalOpen(false);
      if (editingId) {
        showToast(t("assignmentSavedToast"), "success");
      } else {
        setCreatedAssignment(saved);
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("assignmentSaveFailed"), "error");
    }
  }

  async function deleteAssignment(id: string) {
    try {
      // Rückfrage mit Auswahl der eingereichten Dateien (Datenschutz-Audit PRIV-003).
      const result = await requestDelete({
        title: t("deleteAssignmentTitle"),
        message: t("deleteAssignmentConfirm"),
        previewUrl: `/api/submission-assignments/${id}/deletion-preview`,
        deleteUrl: `/api/submission-assignments/${id}/delete`,
      });
      if (!result) return;
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

  // Eine eingereichte Datei endgültig löschen, z. B. auf Wunsch der einreichenden Person (PRIV-003).
  async function deleteSubmittedFile(file: SubmissionFile) {
    const ok = await confirm({ message: t("deleteFileConfirm", { name: file.original_name }), tone: "danger", confirmLabel: t("delete") });
    if (!ok || !selectedId) return;
    try {
      await browserApiFetch(file.content_url.replace(/\/content$/, ""), { method: "DELETE" });
      const data = await refreshElements(selectedId);
      setElementModal((current) => (current ? data.find((el) => el.element_ref === current.element_ref) ?? null : null));
      showToast(t("fileDeletedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("fileDeleteFailed"), "error");
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

  async function restoreWithdrawn(assignmentId: string, elementRef: string) {
    try {
      const updated = await browserApiFetch<SubmissionElementStatusEntry>(
        `/api/submission-assignments/${assignmentId}/elements/${elementRef}/restore-withdrawn`,
        { method: "POST" }
      );
      setElements((current) => current.map((el) => (el.element_ref === elementRef ? updated : el)));
      setElementModal((current) => (current?.element_ref === elementRef ? updated : current));
      showToast(t("withdrawnRestoredToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("withdrawnRestoreFailed"), "error");
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
  const isDoneElement = (el: SubmissionElementStatusEntry) => el.status === "submitted" || el.status === "closed";
  const doneElementCount = elements.filter(isDoneElement).length;
  const visibleElements = elementFilter === "all" ? elements : elements.filter((el) => (elementFilter === "done") === isDoneElement(el));
  const sectionLabel = selectedAssignment?.source_type === "manual" ? t("manualElementsLabel") : selectedAssignment?.source_type === "events" ? t("eventElementsLabel") : t("listElementsLabel");

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
      // Elemente mit eigenem Stichtag (Migration 0198): Anzahl und frühester Stichtag
      const elements = assignment.manual_elements ?? [];
      const next = elements.map((element) => element.window_end).filter((value): value is string => Boolean(value)).sort()[0];
      const deadline = next ? t("deadlineNamed", { date: formatDateShort(next, t) }) : t("noDeadlineOpenUntilClosed");
      return t("sourceSummaryManual", { elements: t("manualElementCount", { count: Math.max(1, elements.length) }), deadline });
    }
    const list = availableLists.find((l) => l.id === assignment.list_definition_id);
    const source = list ? t("sourceListNamed", { name: list.name }) : t("sourceList");
    const deadline = assignment.deadline ? t("deadlineNamed", { date: formatDateShort(assignment.deadline, t) }) : t("noDeadlineOpenUntilClosed");
    return t("sourceSummary", { source, window: deadline });
  }

  const hasNoAssignments = assignments.length === 0;

  return (
    <div className="grid subm-root">
      {deleteModal}
      {/* Header — always visible, including ClamAV status */}
      <div className="page-header subm-page-header">
        <div className="subm-page-intro">
          <h1 className="page-title">{t("pageTitle")}</h1>
          <p className="muted">
            {hasNoAssignments ? t("pageIntroEmpty") : t("pageIntro")}{" "}
            <DocsLink page="abgabebox" anchor="einrichten">{tHelp("guide")}</DocsLink>
          </p>
        </div>
        <div className="table-toolbar-actions">
          <span
            className={`subm-clamav subm-clamav-${clamavStatus}`}
            title={clamavStatus === "offline" ? t("clamavOfflineHint") : undefined}
          >
            <span className="subm-clamav-dot" />
            {clamavStatus === "online" ? t("clamavActive") : clamavStatus === "offline" ? t("clamavOffline") : t("clamavChecking")}
          </span>
          {canManage ? (
            <button type="button" className="button-secondary subm-links-button" aria-label={t("linksCount", { count: links.length })} onClick={() => setLinksModalOpen(true)}>
              {t("linksButton")}
              <span className="subm-list-tab-count">{links.length}</span>
            </button>
          ) : null}
          {hasNoAssignments || !canManage ? null : (
            <button type="button" className="button-primary subm-new-button" onClick={openCreate}>
              {t("newAssignmentPlus")}
            </button>
          )}
        </div>
      </div>

      {hasNoAssignments ? (
        canManage ? (
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
          <EmptyState title={t("readOnly.emptyTitle")} description={t("readOnly.emptyDescription")} />
        )
      ) : (
      <>
      <div className="subm-list-toolbar">
        <div className="tabs-list subm-list-tabs" role="tablist">
          {(["open", "completed"] as const).map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={completion === value}
              className={completion === value ? "tabs-trigger tabs-trigger-active" : "tabs-trigger"}
              onClick={() => setCompletion(value)}
            >
              {t(`completionTabs.${value}`)}
              <span className="subm-list-tab-count">{value === "open" ? assignments.length - completedCount : completedCount}</span>
            </button>
          ))}
        </div>
        <div className="subm-list-search">
          <SearchInput value={search} onChange={setSearch} placeholder={t("searchAssignmentsPlaceholder")} />
        </div>
      </div>

      {filteredAssignments.length === 0 ? (
        <div className="subm-list-empty">
          {search.trim() ? t("noMatches") : completion === "completed" ? t("completedEmpty") : t("openEmpty")}
        </div>
      ) : (
        <div className="subm-list">
          {filteredAssignments.map((assignment) => (
            <article
              key={assignment.id}
              className="subm-card"
              role="button"
              tabIndex={0}
              aria-label={assignment.title}
              onClick={() => void loadElements(assignment.id)}
              onKeyDown={(e) => {
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); void loadElements(assignment.id); }
              }}
            >
              <div className="subm-card-main">
                <div className="subm-card-title-row">
                  <span className="subm-card-title">{assignment.title}</span>
                  {assignment.completed_at ? <Badge variant="success">{t("completedBadge")}</Badge> : null}
                </div>
                <span className="subm-card-meta">{metaLine(assignment)}</span>
              </div>
              <div className="subm-card-progress">
                <SummaryBar summary={summaries[assignment.id]} />
              </div>
              {canManage ? (
                <div className="subm-card-actions">
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
              ) : null}
            </article>
          ))}
        </div>
      )}
      </>
      )}

      {/* Assignment detail popup — participants + progress */}
      <Modal
        open={selectedId !== null}
        onClose={() => { setSelectedId(null); setElementModal(null); }}
        title={selectedAssignment?.title ?? ""}
        description={selectedAssignment ? metaLine(selectedAssignment) : undefined}
        size="wide"
        // Design «Abgaben v4»: direkt aus dem Detail bearbeiten
        headerActions={selectedAssignment && canManage ? (
          <button type="button" className="button-secondary" onClick={() => { const current = selectedAssignment; setSelectedId(null); openEdit(current); }}>
            {t("editAction")}
          </button>
        ) : undefined}
      >
        {selectedId !== null && elementModal ? (
              <div className="grid subm-element-modal">
              <button type="button" className="subm-back-link" onClick={() => setElementModal(null)}>
                ← {sectionLabel}
              </button>
              <div className="subm-element-head">
                <span className="subm-element-title">{elementModal.label}</span>
              </div>
                <div className="status-row">
                  <Badge variant={statusVariant(elementModal)}>{statusLabel(elementModal, t)}</Badge>
                  {elementModal.window_start && elementModal.window_end ? (
                    <span className="subm-modal-meta">{t("windowRange", { start: formatDate(elementModal.window_start), end: formatDate(elementModal.window_end) })}</span>
                  ) : elementModal.window_end ? (
                    <span className="subm-modal-meta">{t("deadlineNamed", { date: formatDate(elementModal.window_end) })}</span>
                  ) : null}
                  {responsibleNames(elementModal) ? (() => {
                    const name = responsibleNames(elementModal);
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
                          {canManage ? (
                            <button
                              type="button"
                              className="button-icon-soft button-icon-soft-danger"
                              aria-label={t("deleteFileAction")}
                              title={t("deleteFileAction")}
                              onClick={() => void deleteSubmittedFile(file)}
                            >
                              <ActionIcon name="delete" />
                            </button>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {elementModal.withdrawn_count ? (
                  <StatusBanner tone="neutral" message={t("withdrawnInfo", { count: elementModal.withdrawn_count })} />
                ) : null}

                <div className="table-toolbar-actions">
                  {elementModal.withdrawn_count && canManage ? (
                    <button
                      type="button"
                      className="button-ghost button-secondary"
                      onClick={() => selectedId && void restoreWithdrawn(selectedId, elementModal.element_ref)}
                    >
                      {t("restoreWithdrawnAction")}
                    </button>
                  ) : null}
                  {!canReview ? null : elementModal.status === "closed" ? (
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
                                <span className="subm-log-time">{formatDateTime(entry.created_at, locale)}</span>
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
        ) : selectedId !== null ? (
          <div className="grid subm-detail">
            <SummaryBar summary={summaries[selectedId]} size="detail" />
            {selectedAssignment && canManage ? <AssignmentLinkField assignment={selectedAssignment} links={links} /> : null}

            {hasPendingFiles && (
              <Badge variant="warning" className="subm-pulse">
                {t("filesInQuarantine")}
              </Badge>
            )}

            <div className="subm-detail-filter-row">
              {elements.length > 0 ? (
                <div className="filter-tabs filter-tabs-chips" role="tablist">
                  {(["all", "done", "pending"] as const).map((value) => (
                    <button
                      key={value}
                      type="button"
                      role="tab"
                      aria-selected={elementFilter === value}
                      className={elementFilter === value ? "filter-tabs-option filter-tabs-option-active" : "filter-tabs-option"}
                      onClick={() => setElementFilter(value)}
                    >
                      {t(`detailFilter.${value}`)}
                      <span className="filter-tabs-count">{value === "all" ? elements.length : value === "done" ? doneElementCount : elements.length - doneElementCount}</span>
                    </button>
                  ))}
                </div>
              ) : null}
              <span className="subm-modal-section-title subm-detail-section-label">{sectionLabel}</span>
            </div>

            {elementsLoading ? (
              <div className="subm-skeleton-box">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="subm-skeleton-row" style={{ animationDelay: `${i * 90}ms` }} />
                ))}
              </div>
            ) : elements.length === 0 ? (
              <p className="muted">{t("noElementsFound")}</p>
            ) : (
              <div className="subm-element-grid">
                {visibleElements.length === 0 ? <p className="muted">{t("noMatches")}</p> : null}
                {visibleElements.map((element) => {
                  const responsibleName = responsibleNames(element) || null;
                  const hasFiles = element.files.length > 0;
                  const variant = statusVariant(element);
                  // Kurzinfo wie im Design: Dateien und Zeitpunkt, sonst die verantwortliche Person
                  const short = hasFiles
                    ? `${t("fileCount", { count: element.files.length })}${element.submitted_at ? ` · ${relativeTime(element.submitted_at, t)}` : ""}`
                    : responsibleName ?? t("notSubmittedYet");
                  return (
                    <button
                      key={element.element_ref}
                      type="button"
                      className="subm-element-card"
                      onClick={() => void openElementModal(selectedId, element)}
                    >
                      <span className={`subm-element-dot subm-element-dot-${variant}`} aria-hidden="true" />
                      <span className="subm-element-text">
                        <span className="subm-element-label">{element.label}</span>
                        <span className="subm-element-short">{short}</span>
                      </span>
                      <Badge variant={variant}>{statusLabel(element, t)}</Badge>
                    </button>
                  );
                })}
              </div>
            )}

            <div className="subm-detail-footer">
              <span className="subm-detail-footer-note">
                <span className="subm-clamav-dot" aria-hidden="true" />
                {t("clamavScanNote")}
              </span>
              <button
                type="button"
                className="button-ghost button-secondary"
                onClick={() => void downloadZip(selectedId)}
                disabled={zipLoading}
                title={t("downloadAllZipTitle")}
              >
                <DownloadIcon /> {zipLoading ? "…" : t("allFilesZip")}
              </button>
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
        availableEvents={availableEvents}
        availableReviewers={availableReviewers}
        availableParticipants={availableParticipants}
        confirmRemoveElement={(name) =>
          confirm({ message: t("wizard.manual.removeConfirm", { name }), tone: "danger", confirmLabel: t("wizard.manual.removeConfirmLabel") })
        }
        onSubmit={submit}
        onClose={() => setModalOpen(false)}
        onManageLinks={openLinksFromForm}
      />

      <SubmissionCreatedModal assignment={createdAssignment} links={links} onClose={() => setCreatedAssignment(null)} />
    </div>
  );
}
