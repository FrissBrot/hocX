"use client";

import { useEffect, useRef, useState } from "react";

import { Badge, BadgeVariant } from "@/components/ui/badge";
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

const LOG_STATUS_LABEL: Record<string, string> = {
  upload_received: "Datei empfangen",
  quarantined: "In Quarantäne gespeichert",
  moved_to_storage: "In Abgabe verschoben",
  submitted: "Freigegeben",
  captcha_failed: "Bot-Check fehlgeschlagen",
  validation_failed: "Validierungsfehler",
  element_closed: "Element geschlossen",
  upload_error: "Upload-Fehler",
  scan_clean: "Scan: Sauber",
  scan_pending: "Scan: Ausstehend (Quarantäne)",
  scan_infected: "Scan: Schadware",
  rescan_clean: "Rescan: Sauber",
  rescan_infected: "Rescan: Schadware",
  rescan_pending: "Rescan: ClamAV offline",
};

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

const SCAN_STATUS_LABEL: Record<string, string> = {
  clean: "Geprüft",
  pending: "Quarantäne",
  infected: "Schadware",
};

const SCAN_STATUS_VARIANT: Record<string, BadgeVariant> = {
  clean: "success",
  pending: "warning",
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

function statusLabel(element: SubmissionElementStatusEntry): string {
  if (element.status === "closed") return "Geschlossen";
  if (element.status === "submitted") {
    if (element.files.some((f) => f.scan_status === "pending")) return "In Quarantäne";
    return "Abgegeben";
  }
  const now = new Date();
  const end = element.window_end ? new Date(element.window_end) : null;
  const start = element.window_start ? new Date(element.window_start) : null;
  if (end && now > end) return "Nicht abgegeben";
  if (start && now < start) return "Ausstehend";
  return "Offen";
}

function statusVariant(element: SubmissionElementStatusEntry): BadgeVariant | null {
  if (element.status === "closed") return "neutral";
  if (element.status === "submitted") {
    if (element.files.some((f) => f.scan_status === "pending")) return "warning";
    return "success";
  }
  return null;
}

function SummaryBar({ summary, size = "row" }: { summary: AssignmentSummary | undefined; size?: "row" | "detail" }) {
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
        <span className="subm-summary-caption">Noch keine Abgaben</span>
      </div>
    );
  }

  const cleanPct = Math.min(100, (clean / denom) * 100);
  const qPct = Math.min(100 - cleanPct, (quarantine / denom) * 100);
  const infPct = Math.min(100 - cleanPct - qPct, (infected / denom) * 100);
  const missingPct = Math.max(0, 100 - cleanPct - qPct - infPct);

  const countLabel = known ? `${sum} von ${total}` : `${sum}`;
  const extraParts = [
    quarantine > 0 ? `${quarantine} Quarantäne` : null,
    infected > 0 ? `${infected} Schadware` : null,
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
        {countLabel} eingereicht{extraParts.length > 0 ? ` · ${extraParts.join(" · ")}` : ""}
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

const MONTHS_DE = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];

function formatDateShort(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return `${String(d.getDate()).padStart(2, "0")}. ${MONTHS_DE[d.getMonth()]} ${d.getFullYear()}`;
}

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const minute = 60_000;
  const hour = 3_600_000;
  const day = 86_400_000;
  if (diffMs < minute) return "gerade eben";
  if (diffMs < hour) {
    const m = Math.max(1, Math.round(diffMs / minute));
    return `vor ${m} Minute${m === 1 ? "" : "n"}`;
  }
  if (diffMs < day) {
    const h = Math.round(diffMs / hour);
    return `vor ${h} Stunde${h === 1 ? "" : "n"}`;
  }
  const d = Math.round(diffMs / day);
  if (d <= 1) return "gestern";
  return `vor ${d} Tagen`;
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" width="14" height="14">
      <path d="M12 3v12m0 0 4.5-4.5M12 15l-4.5-4.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" width="14" height="14">
      <path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
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
              ? `Virenscan: ${result.infected} infizierte Datei(en) gefunden`
              : `Virenscan: ${result.clean} Datei(en) freigegeben`,
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
      showToast(error instanceof Error ? error.message : "Elemente konnten nicht geladen werden", "error");
    } finally {
      setElementsLoading(false);
    }
  }

  useEffect(() => {
    return () => clearRescanTimer();
  }, []);

  async function submit() {
    const isEvents = form.source_type === "events";
    const payload = {
      title: form.title.trim(),
      description: form.description || null,
      public_slug: form.public_slug,
      source_type: form.source_type,
      // Nur was zur gewählten Verknüpfung gehört, wird gesendet – der Rest wird beim Wechsel geleert.
      tag_filter: isEvents ? form.tag_filter : null,
      offset_days_before: isEvents && form.offset_days_before !== "" ? Number(form.offset_days_before) : null,
      offset_days_after: isEvents && form.offset_days_after !== "" ? Number(form.offset_days_after) : null,
      cycle_config_id: isEvents ? form.cycle_config_id || null : null,
      cycle_offsets: isEvents && form.cycle_config_id ? form.cycle_offsets : [],
      list_definition_id: form.source_type === "list" ? form.list_definition_id || null : null,
      deadline: isEvents ? null : form.deadline || null,
      allowed_file_types: form.allowed_file_types,
      max_files_per_element: form.max_files_per_element === "" ? null : Number(form.max_files_per_element),
      max_file_size_mb: Number(form.max_file_size_mb),
      sort_order: form.sort_order,
      responsible_participant_source: form.source_type === "manual" ? null : form.responsible_participant_source || null,
      link_ids: form.link_ids,
    };

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
      showToast(editingId ? "Abgabe gespeichert" : "Abgabe erstellt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Abgabe konnte nicht gespeichert werden", "error");
    }
  }

  async function deleteAssignment(id: string) {
    const ok = await confirm({
      message: "Abgabe wirklich löschen? Alle zugehörigen Elemente und Verweise werden entfernt.",
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
      showToast("Abgabe gelöscht", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Abgabe konnte nicht gelöscht werden", "error");
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
      showToast(error instanceof Error ? error.message : "Download fehlgeschlagen", "error");
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
      showToast(error instanceof Error ? error.message : "Download fehlgeschlagen", "error");
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
      showToast("Log konnte nicht geladen werden", "error");
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
      showToast("Element wieder aufgeschaltet", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Element konnte nicht wieder aufgeschaltet werden", "error");
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
      showToast("Element geschlossen", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Element konnte nicht geschlossen werden", "error");
    }
  }

  const selectedAssignment = assignments.find((a) => a.id === selectedId);
  const hasPendingFiles = elements.some((el) => el.files.some((f) => f.scan_status === "pending"));

  function metaLine(assignment: SubmissionAssignment): string {
    if (assignment.source_type === "events") {
      const cycleConfig = availableCycleConfigs.find((c) => c.id === assignment.cycle_config_id);
      const cycles = cycleConfig
        ? ` (${cycleConfig.name}: ${[...assignment.cycle_offsets].sort((a, b) => b - a).map(cycleOffsetLabel).join(", ")})`
        : "";
      const source = (assignment.tag_filter ? `Termin „${assignment.tag_filter}“` : "Termine") + cycles;
      const before = assignment.offset_days_before;
      const after = assignment.offset_days_after;
      const windowParts = [
        before !== null ? `ab ${before} Tage vorher` : null,
        after !== null ? `bis ${after} Tage danach` : null,
      ].filter((v): v is string => Boolean(v));
      const window = windowParts.length > 0 ? windowParts.join(", ") : "kein Zeitfenster (offen bis manuell geschlossen)";
      return `Quelle: ${source} · ${window}`;
    }
    if (assignment.source_type === "manual") {
      const deadline = assignment.deadline ? `Deadline ${formatDateShort(assignment.deadline)}` : "Kein Stichtag (offen bis manuell geschlossen)";
      return `Quelle: Manuell · ${deadline}`;
    }
    const list = availableLists.find((l) => l.id === assignment.list_definition_id);
    const source = list ? `Liste „${list.name}“` : "Liste";
    const deadline = assignment.deadline ? `Deadline ${formatDateShort(assignment.deadline)}` : "Kein Stichtag (offen bis manuell geschlossen)";
    return `Quelle: ${source} · ${deadline}`;
  }

  const hasNoAssignments = assignments.length === 0;

  return (
    <div className="grid subm-root">
      {/* Header — always visible, including ClamAV status */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Abgaben</h1>
          <p className="muted">{hasNoAssignments ? "Öffentliche Abgabeboxen für Dokumente und Formulare." : "Externe Abgaben ohne Anmeldung — gekoppelt an Termine oder eine Liste, oder manuell."}</p>
        </div>
        <div className="subm-toolbar-actions">
          <span className={`subm-clamav subm-clamav-${clamavStatus}`}>
            <span className="subm-clamav-dot" />
            ClamAV {clamavStatus === "online" ? "Online" : clamavStatus === "offline" ? "Offline" : "…"}
          </span>
          <button type="button" className="button-ghost" onClick={() => setLinksModalOpen(true)}>
            Links ({links.length})
          </button>
          {hasNoAssignments ? null : (
            <button type="button" className="button-secondary subm-new-button" onClick={openCreate}>
              <PlusIcon /> Abgabe
            </button>
          )}
        </div>
      </div>

      {hasNoAssignments ? (
        <EmptyState
          title="Keine Abgaben eingerichtet"
          description="Mit einer Abgabebox sammelst du Dokumente und Bilder über einen öffentlichen Link – ohne Login für die Einreichenden."
          actions={
            <button type="button" className="button-primary" onClick={openCreate}>
              + Abgabe
            </button>
          }
          hint="Eingereichte Bilder landen automatisch in der Fotogalerie, Dokumente unter Dateien."
        />
      ) : (
      <>
      <div className="list-filter-row">
        <div />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder="Abgaben suchen…" />
        </div>
      </div>

      <DataTable
        className="data-table-lg"
        columns={["Titel", "Quelle / Zeitraum", "Fortschritt", "Aktionen"]}
        emptyMessage="Keine Treffer"
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
                    aria-label="Bearbeiten"
                    title="Bearbeiten"
                  >
                    ✎
                  </button>
                  <button
                    type="button"
                    className="subm-sidebar-icon-button subm-sidebar-icon-button-danger"
                    onClick={(e) => { e.stopPropagation(); void deleteAssignment(assignment.id); }}
                    aria-label="Löschen"
                    title="Löschen"
                  >
                    ×
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
                Dateien in Quarantäne
              </Badge>
            )}

            <div className="subm-modal-section-title">{selectedAssignment?.source_type === "manual" ? "Abgabe" : "Teilnehmer"}</div>

            {elementsLoading ? (
              <div className="subm-skeleton-box">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="subm-skeleton-row" style={{ animationDelay: `${i * 90}ms` }} />
                ))}
              </div>
            ) : elements.length === 0 ? (
              <p className="muted">Keine Elemente gefunden.</p>
            ) : (
              <div className="subm-participant-list">
                {elements.map((element, rowIndex) => {
                  const responsibleName = element.responsible_participant_id
                    ? (availableParticipants.find((p) => p.id === element.responsible_participant_id)?.display_name ?? "Unbekannter Teilnehmer")
                    : null;
                  const displayName = responsibleName ?? element.label;
                  const hasFiles = element.files.length > 0;
                  const variant = statusVariant(element);
                  const label = statusLabel(element);
                  const meta = hasFiles
                    ? `${element.files.length} Datei${element.files.length === 1 ? "" : "en"}${element.submitted_at ? ` · ${relativeTime(element.submitted_at)}` : ""}`
                    : "Noch nicht eingereicht";
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
                title="Alle geprüften Dateien als ZIP herunterladen"
              >
                <DownloadIcon /> {zipLoading ? "…" : "Alle Dateien (.zip)"}
              </button>
              <button type="button" className="button-secondary" onClick={() => setSelectedId(null)}>
                Schliessen
              </button>
            </div>
          </div>
        ) : null}
      </Modal>

      {/* Element detail popup — files + log combined */}
      <Modal
        open={elementModal !== null}
        onClose={() => setElementModal(null)}
        title={elementModal?.label ?? "Element"}
        size="wide"
      >
        {elementModal ? (
          <div className="grid subm-element-modal">
            <div className="status-row">
              {statusVariant(elementModal) ? (
                <Badge variant={statusVariant(elementModal)!}>{statusLabel(elementModal)}</Badge>
              ) : (
                <Badge variant="neutral">{statusLabel(elementModal)}</Badge>
              )}
              {elementModal.window_start && elementModal.window_end ? (
                <span className="subm-modal-meta">{elementModal.window_start} – {elementModal.window_end}</span>
              ) : elementModal.window_end ? (
                <span className="subm-modal-meta">Frist: {elementModal.window_end}</span>
              ) : null}
              {elementModal.responsible_participant_id ? (() => {
                const name = availableParticipants.find((p) => p.id === elementModal.responsible_participant_id)?.display_name
                  ?? "Unbekannter Teilnehmer";
                return (
                  <span className="subm-responsible">
                    <span className="subm-avatar">{initials(name)}</span>
                    {name}
                  </span>
                );
              })() : null}
            </div>

            <div className="subm-modal-section">
              <div className="subm-modal-section-title">Dateien</div>
              {elementModal.files.length === 0 ? (
                <p className="muted">Keine Dateien vorhanden.</p>
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
                          <span className="subm-verified" title="Geprüft">
                            <VerifiedIcon />
                          </span>
                          <button
                            type="button"
                            className="subm-file-download-button"
                            title="Datei herunterladen"
                            onClick={() => void downloadFile(file.content_url, file.original_name)}
                          >
                            <DownloadIcon />
                          </button>
                        </>
                      ) : (
                        <Badge variant={SCAN_STATUS_VARIANT[file.scan_status] ?? "neutral"}>
                          {SCAN_STATUS_LABEL[file.scan_status] ?? file.scan_status}
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
                  Wieder aufschalten
                </button>
              ) : (
                <button
                  type="button"
                  className="button-ghost button-secondary subm-close-button"
                  onClick={() => selectedId && void closeElement(selectedId, elementModal.element_ref)}
                >
                  Element schliessen
                </button>
              )}
            </div>

            <div className="subm-modal-section">
              <div className="subm-modal-section-title">Log</div>
              {logLoading ? (
                <p className="muted">Lädt…</p>
              ) : logEntries.length === 0 ? (
                <p className="muted">Keine Einträge vorhanden.</p>
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
                            <Badge variant={variant}>{LOG_STATUS_LABEL[entry.status] ?? entry.status}</Badge>
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
        title="Abgabe-Links"
        description="Über diese Links ist die öffentliche Abgabebox erreichbar."
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
