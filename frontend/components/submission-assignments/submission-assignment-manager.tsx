"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import {
  AssignmentSummary,
  EventSummary,
  ParticipantSummary,
  StructuredListDefinition,
  SubmissionAssignment,
  SubmissionElementStatusEntry,
  SubmissionSourceType,
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

const LOG_STATUS_CLASS: Record<string, string> = {
  upload_received: "",
  quarantined: "pill-warning",
  moved_to_storage: "pill-success",
  submitted: "pill-success",
  captcha_failed: "pill-warning",
  validation_failed: "pill-warning",
  element_closed: "pill-warning",
  upload_error: "pill-error",
  scan_clean: "pill-success",
  scan_pending: "pill-warning",
  scan_infected: "pill-error",
  rescan_clean: "pill-success",
  rescan_infected: "pill-error",
  rescan_pending: "pill-warning",
};

const SCAN_STATUS_LABEL: Record<string, string> = {
  clean: "Geprüft",
  pending: "Quarantäne",
  infected: "Schadware",
};

const SCAN_STATUS_CLASS: Record<string, string> = {
  clean: "pill-success",
  pending: "pill-warning",
  infected: "pill-error",
};

const SINGLE_PARTICIPANT_EVENT_FIELDS: { field: string; label: string }[] = [
  { field: "spezial1_ids", label: "Spezial 1" },
  { field: "spezial2_ids", label: "Spezial 2" },
  { field: "spezial3_ids", label: "Spezial 3" },
];

type Props = {
  initialAssignments: SubmissionAssignment[];
  availableLists: StructuredListDefinition[];
  availableEvents: EventSummary[];
  availableParticipants: ParticipantSummary[];
};

type FormState = {
  title: string;
  description: string;
  public_slug: string;
  source_type: SubmissionSourceType;
  tag_filter: string;
  offset_days_before: number | "";
  offset_days_after: number | "";
  list_definition_id: number | "";
  deadline: string;
  allowed_file_types: string[];
  max_files_per_element: number;
  max_file_size_mb: number;
  is_active: boolean;
  responsible_participant_source: string;
};

const FILE_TYPE_GROUPS = [
  { label: "PDF", types: ["pdf"] },
  { label: "Office-Dateien", types: ["doc", "docx", "xls", "xlsx", "ppt", "pptx"] },
  { label: "Bilddateien", types: ["jpg", "jpeg", "png", "gif", "webp"] },
];

const initialForm: FormState = {
  title: "",
  description: "",
  public_slug: "",
  source_type: "events",
  tag_filter: "",
  offset_days_before: "",
  offset_days_after: "",
  list_definition_id: "",
  deadline: "",
  allowed_file_types: [],
  max_files_per_element: 1,
  max_file_size_mb: 20,
  is_active: true,
  responsible_participant_source: "",
};

function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function formFromAssignment(assignment: SubmissionAssignment): FormState {
  return {
    title: assignment.title,
    description: assignment.description ?? "",
    public_slug: assignment.public_slug,
    source_type: assignment.source_type,
    tag_filter: assignment.tag_filter ?? "",
    offset_days_before: assignment.offset_days_before ?? "",
    offset_days_after: assignment.offset_days_after ?? "",
    list_definition_id: assignment.list_definition_id ?? "",
    deadline: assignment.deadline ?? "",
    allowed_file_types: assignment.allowed_file_types,
    max_files_per_element: assignment.max_files_per_element,
    max_file_size_mb: assignment.max_file_size_mb,
    is_active: assignment.is_active,
    responsible_participant_source: assignment.responsible_participant_source ?? "",
  };
}

function statusLabel(element: SubmissionElementStatusEntry): string {
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

function statusClass(element: SubmissionElementStatusEntry): string {
  if (element.status === "submitted") {
    if (element.files.some((f) => f.scan_status === "pending")) return "pill-warning";
    return "pill-success";
  }
  return "";
}

function SummaryBar({ summary }: { summary: AssignmentSummary | undefined }) {
  if (!summary) {
    return <div className="subm-summary-track" />;
  }
  const { submitted, quarantine, infected, total } = summary;
  const clean = Math.max(0, submitted);

  if (total !== null && total > 0) {
    const cleanPct = Math.min(100, (clean / total) * 100);
    const qPct = Math.min(100 - cleanPct, (quarantine / total) * 100);
    const infPct = Math.min(100 - cleanPct - qPct, (infected / total) * 100);
    const missingPct = Math.max(0, 100 - cleanPct - qPct - infPct);
    const label = `${clean + quarantine + infected}/${total}`;
    return (
      <div className="subm-summary">
        <div className="subm-summary-track">
          {cleanPct > 0 && <div className="subm-summary-segment subm-summary-segment-clean" style={{ width: `${cleanPct}%` }} />}
          {qPct > 0 && <div className="subm-summary-segment subm-summary-segment-quarantine" style={{ width: `${qPct}%` }} />}
          {infPct > 0 && <div className="subm-summary-segment subm-summary-segment-infected" style={{ width: `${infPct}%` }} />}
          {missingPct > 0 && <div className="subm-summary-segment" style={{ width: `${missingPct}%` }} />}
        </div>
        <span className="subm-summary-caption">
          {label} abgegeben
          {quarantine > 0 ? ` · ${quarantine} Quarantäne` : ""}
          {infected > 0 ? ` · ${infected} Schadware` : ""}
        </span>
      </div>
    );
  }

  const total2 = clean + quarantine + infected;
  if (total2 === 0) {
    return (
      <div className="subm-summary">
        <div className="subm-summary-track" />
        <span className="subm-summary-caption">Noch keine Abgaben</span>
      </div>
    );
  }
  return (
    <div className="subm-summary">
      <div className="subm-summary-track">
        {clean > 0 && <div className="subm-summary-segment subm-summary-segment-clean" style={{ flex: clean }} />}
        {quarantine > 0 && <div className="subm-summary-segment subm-summary-segment-quarantine" style={{ flex: quarantine }} />}
        {infected > 0 && <div className="subm-summary-segment subm-summary-segment-infected" style={{ flex: infected }} />}
      </div>
      <span className="subm-summary-caption">
        {total2} abgegeben
        {quarantine > 0 ? ` · ${quarantine} Quarantäne` : ""}
        {infected > 0 ? ` · ${infected} Schadware` : ""}
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

export function SubmissionAssignmentManager({ initialAssignments, availableLists, availableEvents, availableParticipants }: Props) {
  const showToast = useToast();
  const [assignments, setAssignments] = useState(initialAssignments);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(initialForm);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [zipLoading, setZipLoading] = useState(false);
  const [elements, setElements] = useState<SubmissionElementStatusEntry[]>([]);
  const [elementsLoading, setElementsLoading] = useState(false);
  const [clamavStatus, setClamavStatus] = useState<"online" | "offline" | "unknown">("unknown");
  const [summaries, setSummaries] = useState<Record<number, AssignmentSummary>>({});
  const [hoveredAssignmentId, setHoveredAssignmentId] = useState<number | null>(null);
  const rescanTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [elementModal, setElementModal] = useState<SubmissionElementStatusEntry | null>(null);
  const [logEntries, setLogEntries] = useState<SubmissionUploadLogEntry[]>([]);
  const [logLoading, setLogLoading] = useState(false);
  const [search, setSearch] = useState("");

  const availableTags = Array.from(
    new Set(availableEvents.map((e) => e.tag).filter((t): t is string => Boolean(t)))
  ).sort();

  const [tagDropdownOpen, setTagDropdownOpen] = useState(false);
  const [tagDropdownSearch, setTagDropdownSearch] = useState("");
  const tagDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!tagDropdownOpen) return;
    function handleClick(e: MouseEvent) {
      if (tagDropdownRef.current && !tagDropdownRef.current.contains(e.target as Node)) {
        setTagDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [tagDropdownOpen]);

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

  const filteredTags = tagDropdownSearch.trim()
    ? availableTags.filter((t) => t.toLowerCase().includes(tagDropdownSearch.toLowerCase()))
    : availableTags;

  const filteredAssignments = search.trim()
    ? assignments.filter((a) => a.title.toLowerCase().includes(search.toLowerCase()))
    : assignments;

  function openCreate() {
    setEditingId(null);
    setForm(initialForm);
    setModalOpen(true);
  }

  function openEdit(assignment: SubmissionAssignment) {
    setEditingId(assignment.id);
    setForm(formFromAssignment(assignment));
    setModalOpen(true);
  }

  function toggleFileType(type: string) {
    setForm((c) => ({
      ...c,
      allowed_file_types: c.allowed_file_types.includes(type)
        ? c.allowed_file_types.filter((t) => t !== type)
        : [...c.allowed_file_types, type],
    }));
  }

  function clearRescanTimer() {
    if (rescanTimerRef.current !== null) {
      clearTimeout(rescanTimerRef.current);
      rescanTimerRef.current = null;
    }
  }

  async function refreshElements(assignmentId: number): Promise<SubmissionElementStatusEntry[]> {
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

  async function scheduleAutoRescan(assignmentId: number, delayMs = 5000) {
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

  async function loadElements(assignmentId: number) {
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

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const payload =
      form.source_type === "events"
        ? {
            title: form.title,
            description: form.description || null,
            public_slug: form.public_slug,
            source_type: "events" as const,
            tag_filter: form.tag_filter,
            offset_days_before: form.offset_days_before === "" ? 0 : Number(form.offset_days_before),
            offset_days_after: form.offset_days_after === "" ? 0 : Number(form.offset_days_after),
            list_definition_id: null,
            deadline: null,
            allowed_file_types: form.allowed_file_types,
            max_files_per_element: Number(form.max_files_per_element),
            max_file_size_mb: Number(form.max_file_size_mb),
            is_active: form.is_active,
            responsible_participant_source: form.responsible_participant_source || null,
          }
        : {
            title: form.title,
            description: form.description || null,
            public_slug: form.public_slug,
            source_type: "list" as const,
            tag_filter: null,
            offset_days_before: null,
            offset_days_after: null,
            list_definition_id: form.list_definition_id === "" ? null : Number(form.list_definition_id),
            deadline: form.deadline,
            allowed_file_types: form.allowed_file_types,
            max_files_per_element: Number(form.max_files_per_element),
            max_file_size_mb: Number(form.max_file_size_mb),
            is_active: form.is_active,
            responsible_participant_source: form.responsible_participant_source || null,
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

  async function deleteAssignment(id: number) {
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

  async function downloadZip(assignmentId: number) {
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

  async function openElementModal(assignmentId: number, element: SubmissionElementStatusEntry) {
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

  async function reopenElement(assignmentId: number, elementRef: string) {
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

  const selectedAssignment = assignments.find((a) => a.id === selectedId);
  const hasPendingFiles = elements.some((el) => el.files.some((f) => f.scan_status === "pending"));

  return (
    <div className="grid subm-root">
      {/* Toolbar — always visible, including ClamAV status */}
      <DataToolbar
        title="Abgaben"
        description="Externe Abgaben ohne Anmeldung — gekoppelt an Termine oder eine Liste."
        actions={
          <div className="subm-toolbar-actions">
            <span className={`subm-clamav subm-clamav-${clamavStatus}`}>
              <span className="subm-clamav-dot" />
              ClamAV {clamavStatus === "online" ? "Online" : clamavStatus === "offline" ? "Offline" : "…"}
            </span>
            <button type="button" className="button-inline subm-new-button" onClick={openCreate}>
              <PlusIcon /> Neue Abgabe
            </button>
          </div>
        }
      />

      {/* Split layout */}
      <div className="subm-layout">

        {/* Left sidebar — assignment list */}
        <aside className="subm-sidebar">
          <input
            className="subm-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Abgaben suchen…"
          />

          <div className="subm-sidebar-list">
            {filteredAssignments.length === 0 ? (
              <span className="subm-sidebar-empty">
                {assignments.length === 0 ? "Noch keine Abgaben" : "Keine Treffer"}
              </span>
            ) : filteredAssignments.map((assignment, index) => {
              const isSelected = selectedId === assignment.id;
              const isHovered = hoveredAssignmentId === assignment.id;
              return (
                <div
                  key={assignment.id}
                  className="subm-sidebar-item"
                  style={{ animationDelay: `${Math.min(index, 12) * 28}ms` }}
                  onMouseEnter={() => setHoveredAssignmentId(assignment.id)}
                  onMouseLeave={() => setHoveredAssignmentId(null)}
                >
                  <button
                    type="button"
                    onClick={() => void loadElements(assignment.id)}
                    className={`subm-sidebar-item-button${isSelected ? " subm-sidebar-item-active" : ""}${isHovered && !isSelected ? " subm-sidebar-item-hover-actions" : ""}`}
                  >
                    <div className="subm-sidebar-item-title">
                      {assignment.title}
                    </div>
                    <div className="subm-sidebar-item-meta">
                      <span className="subm-sidebar-item-type">
                        {assignment.source_type === "events" ? "Termine" : "Liste"}
                      </span>
                      {!assignment.is_active && (
                        <span className="subm-sidebar-item-inactive">· Inaktiv</span>
                      )}
                    </div>
                    <SummaryBar summary={summaries[assignment.id]} />
                  </button>

                  {isHovered && !isSelected && (
                    <div className="subm-sidebar-item-actions">
                      <button
                        type="button"
                        className="subm-sidebar-icon-button"
                        onClick={(e) => { e.stopPropagation(); openEdit(assignment); }}
                        aria-label="Bearbeiten"
                      >
                        ✎
                      </button>
                      <button
                        type="button"
                        className="subm-sidebar-icon-button subm-sidebar-icon-button-danger"
                        onClick={(e) => { e.stopPropagation(); void deleteAssignment(assignment.id); }}
                        aria-label="Löschen"
                      >
                        ×
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </aside>

        {/* Right panel — elements */}
        <section className="subm-panel">
          {selectedId === null ? (
            <div className="subm-panel-empty">
              <div className="subm-panel-empty-icon">
                <FileIcon />
              </div>
              Abgabe auswählen
            </div>
          ) : (
            <div key={selectedId} className="subm-panel-content">
              {/* Panel header */}
              <div className="subm-panel-header">
                <div className="subm-panel-heading">
                  <h2 className="subm-panel-title">{selectedAssignment?.title}</h2>
                  {hasPendingFiles && (
                    <span className="pill pill-sm pill-warning subm-pulse">
                      Dateien in Quarantäne
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  className="subm-zip-button"
                  onClick={() => void downloadZip(selectedId)}
                  disabled={zipLoading}
                  title="Alle geprüften Dateien als ZIP herunterladen"
                >
                  <DownloadIcon /> {zipLoading ? "…" : "ZIP"}
                </button>
              </div>

              {/* Elements table */}
              {elementsLoading ? (
                <div className="subm-table-box subm-skeleton-box">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="subm-skeleton-row" style={{ animationDelay: `${i * 90}ms` }} />
                  ))}
                </div>
              ) : elements.length === 0 ? (
                <p className="muted">Keine Elemente gefunden.</p>
              ) : (
                <div className="subm-table-box">
                  <table className="subm-table">
                    <thead>
                      <tr>
                        {["Element", "Verantwortlich", "Fenster/Frist", "Status", "Dateien"].map((col) => (
                          <th key={col}>{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {elements.map((element, rowIndex) => {
                        const responsibleName = element.responsible_participant_id
                          ? (availableParticipants.find((p) => p.id === element.responsible_participant_id)?.display_name ?? `#${element.responsible_participant_id}`)
                          : null;
                        return (
                          <tr
                            key={element.element_ref}
                            className="subm-table-row subm-table-row-clickable"
                            style={{ animationDelay: `${Math.min(rowIndex, 14) * 25}ms` }}
                            onClick={() => void openElementModal(selectedId, element)}
                          >
                            <td className="subm-element-title">{element.label}</td>
                            <td>
                              {responsibleName ? (
                                <span className="subm-responsible">
                                  <span className="subm-avatar">{initials(responsibleName)}</span>
                                  {responsibleName}
                                </span>
                              ) : (
                                <span className="subm-empty-cell">—</span>
                              )}
                            </td>
                            <td className="subm-window-cell">
                              {element.window_start && element.window_end
                                ? `${element.window_start} – ${element.window_end}`
                                : element.window_end ?? "—"}
                            </td>
                            <td className="subm-status-cell">
                              {statusClass(element) ? (
                                <span className={`pill pill-sm ${statusClass(element)}`}>{statusLabel(element)}</span>
                              ) : (
                                <span className="subm-empty-cell">{statusLabel(element)}</span>
                              )}
                            </td>
                            <td className="subm-status-cell">
                              {element.files.length === 0 ? (
                                <span className="subm-empty-cell">—</span>
                              ) : (
                                <span className="subm-file-count">
                                  <FileIcon /> {element.files.length}
                                </span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </section>
      </div>

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
              {statusClass(elementModal) ? (
                <span className={`pill pill-sm ${statusClass(elementModal)}`}>{statusLabel(elementModal)}</span>
              ) : (
                <span className="pill pill-sm">{statusLabel(elementModal)}</span>
              )}
              {elementModal.window_start && elementModal.window_end ? (
                <span className="subm-modal-meta">{elementModal.window_start} – {elementModal.window_end}</span>
              ) : elementModal.window_end ? (
                <span className="subm-modal-meta">Frist: {elementModal.window_end}</span>
              ) : null}
              {elementModal.responsible_participant_id ? (() => {
                const name = availableParticipants.find((p) => p.id === elementModal.responsible_participant_id)?.display_name
                  ?? `#${elementModal.responsible_participant_id}`;
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
                        <span className={`pill pill-sm ${SCAN_STATUS_CLASS[file.scan_status] ?? ""}`}>
                          {SCAN_STATUS_LABEL[file.scan_status] ?? file.scan_status}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {elementModal.status === "submitted" ? (
              <div className="table-toolbar-actions">
                <button
                  type="button"
                  className="button-ghost button-inline subm-reopen-button"
                  onClick={() => selectedId && void reopenElement(selectedId, elementModal.element_ref)}
                >
                  Wieder aufschalten
                </button>
              </div>
            ) : null}

            <div className="subm-modal-section">
              <div className="subm-modal-section-title">Log</div>
              {logLoading ? (
                <p className="muted">Lädt…</p>
              ) : logEntries.length === 0 ? (
                <p className="muted">Keine Einträge vorhanden.</p>
              ) : (
                <div className="subm-log-list">
                  {logEntries.map((entry) => {
                    const tone = (LOG_STATUS_CLASS[entry.status] ?? "").replace("pill-", "") || "neutral";
                    return (
                      <div key={entry.id} className={`subm-log-entry subm-log-entry-${tone}`}>
                        <span className="subm-log-dot" />
                        <div className="subm-log-body">
                          <div className="subm-log-header">
                            <span className={`pill pill-sm ${LOG_STATUS_CLASS[entry.status] ?? ""}`}>
                              {LOG_STATUS_LABEL[entry.status] ?? entry.status}
                            </span>
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

      {/* Create/Edit Modal */}
      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editingId ? "Abgabe bearbeiten" : "Abgabe erstellen"}
        description="Termin-Abgaben nutzen ein Zeitfenster relativ zum Termin, Listen-Abgaben einen festen Stichtag."
      >
        <form className="grid" onSubmit={submit}>
          <label className="field-stack">
            <span className="field-label">Titel</span>
            <input
              value={form.title}
              onChange={(e) => {
                const title = e.target.value;
                setForm((c) => ({
                  ...c,
                  title,
                  ...(editingId === null ? { public_slug: slugify(title) } : {}),
                }));
              }}
              required
            />
          </label>

          <label className="field-stack">
            <span className="field-label">Beschreibung</span>
            <input
              value={form.description}
              onChange={(e) => setForm((c) => ({ ...c, description: e.target.value }))}
              placeholder="Optional"
            />
          </label>

          <label className="field-stack">
            <span className="field-label">Verknüpfung</span>
            <select
              value={form.source_type}
              onChange={(e) => setForm((c) => ({ ...c, source_type: e.target.value as SubmissionSourceType }))}
            >
              <option value="events">Termine (per Tag-Filter)</option>
              <option value="list">Liste (mit Stichtag)</option>
            </select>
          </label>

          {form.source_type === "events" ? (
            <div className="two-col">
              <div className="field-stack">
                <span className="field-label">Tag-Filter</span>
                <div ref={tagDropdownRef} style={{ position: "relative" }}>
                  <button
                    type="button"
                    onClick={() => { setTagDropdownOpen((v) => !v); setTagDropdownSearch(""); }}
                    style={{ width: "100%", textAlign: "left", padding: "12px 14px", borderRadius: 16, border: "1px solid var(--border)", background: "color-mix(in srgb, var(--panel-solid) 92%, transparent 8%)", color: form.tag_filter ? "var(--text)" : "var(--muted)", cursor: "pointer", minHeight: 48, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6, fontSize: "inherit", boxSizing: "border-box" }}
                  >
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {form.tag_filter || "Tag wählen…"}
                    </span>
                    <span style={{ flexShrink: 0, opacity: 0.5 }}>▾</span>
                  </button>
                  {tagDropdownOpen && (
                    <div style={{ position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0, zIndex: 200, backgroundColor: "var(--panel-solid)", border: "1px solid var(--border)", borderRadius: 10, boxShadow: "0 6px 20px rgba(0,0,0,0.2)", overflow: "hidden" }}>
                      <div style={{ padding: "6px 8px", borderBottom: "1px solid var(--border)" }}>
                        <input
                          autoFocus
                          type="text"
                          placeholder="Suchen…"
                          value={tagDropdownSearch}
                          onChange={(e) => setTagDropdownSearch(e.target.value)}
                          style={{ width: "100%", boxSizing: "border-box", padding: "6px 10px", borderRadius: 6, border: "1px solid var(--border)", backgroundColor: "var(--surface)", color: "var(--text)", fontSize: "0.88rem", minHeight: 0, outline: "none" }}
                        />
                      </div>
                      <div style={{ maxHeight: 220, overflowY: "auto", padding: "4px 0" }}>
                        {filteredTags.length === 0 ? (
                          <div style={{ padding: "8px 12px", fontSize: "0.88rem", color: "var(--muted)" }}>Keine Tags gefunden</div>
                        ) : filteredTags.map((tag) => (
                          <button
                            key={tag}
                            type="button"
                            onClick={() => { setForm((c) => ({ ...c, tag_filter: tag })); setTagDropdownOpen(false); }}
                            style={{ display: "block", width: "100%", textAlign: "left", padding: "8px 14px", background: "none", border: "none", color: "var(--text)", cursor: "pointer", fontSize: "0.9rem", minHeight: 0, fontWeight: form.tag_filter === tag ? 700 : 400 }}
                          >
                            {tag}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
              <div className="two-col">
                <label className="field-stack">
                  <span className="field-label">Tage vor Termin (ab)</span>
                  <input
                    type="number"
                    min={0}
                    value={form.offset_days_before}
                    onChange={(e) => setForm((c) => ({ ...c, offset_days_before: e.target.value === "" ? "" : Number(e.target.value) }))}
                    required
                  />
                </label>
                <label className="field-stack">
                  <span className="field-label">Tage nach Termin (bis)</span>
                  <input
                    type="number"
                    min={0}
                    value={form.offset_days_after}
                    onChange={(e) => setForm((c) => ({ ...c, offset_days_after: e.target.value === "" ? "" : Number(e.target.value) }))}
                    required
                  />
                </label>
              </div>
            </div>
          ) : (
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">Liste</span>
                <select
                  value={form.list_definition_id}
                  onChange={(e) => setForm((c) => ({ ...c, list_definition_id: e.target.value ? Number(e.target.value) : "" }))}
                  required
                >
                  <option value="">Liste wählen…</option>
                  {availableLists.map((list) => (
                    <option key={list.id} value={list.id}>
                      {list.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field-stack">
                <span className="field-label">Stichtag</span>
                <input
                  type="date"
                  value={form.deadline}
                  onChange={(e) => setForm((c) => ({ ...c, deadline: e.target.value }))}
                  required
                />
              </label>
            </div>
          )}

          {(() => {
            const selectedList = form.source_type === "list" && form.list_definition_id !== ""
              ? availableLists.find((l) => l.id === Number(form.list_definition_id))
              : null;
            const listParticipantCols: { value: string; label: string }[] = [];
            if (selectedList) {
              if (selectedList.column_one_value_type === "participant")
                listParticipantCols.push({ value: "column_one", label: selectedList.column_one_title || "Spalte 1" });
              if (selectedList.column_two_value_type === "participant")
                listParticipantCols.push({ value: "column_two", label: selectedList.column_two_title || "Spalte 2" });
            }
            const eventOptions = form.source_type === "events" ? SINGLE_PARTICIPANT_EVENT_FIELDS : [];
            const options = form.source_type === "events" ? eventOptions : listParticipantCols;
            if (options.length === 0) return null;
            return (
              <label className="field-stack">
                <span className="field-label">Verantwortliche Person</span>
                <select
                  value={form.responsible_participant_source}
                  onChange={(e) => setForm((c) => ({ ...c, responsible_participant_source: e.target.value }))}
                >
                  <option value="">Keine Zuweisung</option>
                  {options.map((opt) => {
                    const val = "field" in opt ? opt.field : opt.value;
                    return <option key={val} value={val}>{opt.label}</option>;
                  })}
                </select>
                <span className="field-help">Das Feld, das die verantwortliche Person für diese Abgabe enthält.</span>
              </label>
            );
          })()}

          <div className="field-stack">
            <span className="field-label">Erlaubte Dateitypen</span>
            <div style={{ display: "flex", flexDirection: "column", gap: 0, border: "1px solid var(--border)", borderRadius: 12, overflow: "hidden" }}>
              {FILE_TYPE_GROUPS.map((group, gi) => {
                const allChecked = group.types.every((t) => form.allowed_file_types.includes(t));
                const someChecked = group.types.some((t) => form.allowed_file_types.includes(t));
                return (
                  <div key={group.label} style={{ padding: "10px 14px", borderTop: gi > 0 ? "1px solid var(--border)" : undefined }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7 }}>
                      <span style={{ fontSize: "0.78rem", fontWeight: 700, color: "var(--text)", textTransform: "uppercase", letterSpacing: "0.05em", flex: 1 }}>
                        {group.label}
                      </span>
                      {group.types.length > 1 && (
                        <label className="checkbox-line" style={{ margin: 0, minHeight: 0, fontSize: "0.8rem", color: "var(--muted)" }}>
                          <input
                            type="checkbox"
                            checked={allChecked}
                            ref={(el) => { if (el) el.indeterminate = someChecked && !allChecked; }}
                            onChange={() => {
                              const toAdd = allChecked ? [] : group.types;
                              setForm((c) => ({
                                ...c,
                                allowed_file_types: [
                                  ...c.allowed_file_types.filter((t) => !group.types.includes(t)),
                                  ...toAdd,
                                ],
                              }));
                            }}
                          />
                          Alle
                        </label>
                      )}
                    </div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "5px 14px" }}>
                      {group.types.map((type) => (
                        <label key={type} className="checkbox-line" style={{ margin: 0, minHeight: 0 }}>
                          <input
                            type="checkbox"
                            checked={form.allowed_file_types.includes(type)}
                            onChange={() => toggleFileType(type)}
                          />
                          .{type}
                        </label>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Max. Dateien</span>
              <input
                type="number"
                min={1}
                value={form.max_files_per_element}
                onChange={(e) => setForm((c) => ({ ...c, max_files_per_element: Number(e.target.value) }))}
              />
            </label>
            <label className="field-stack">
              <span className="field-label">Max. Größe (MB)</span>
              <input
                type="number"
                min={1}
                value={form.max_file_size_mb}
                onChange={(e) => setForm((c) => ({ ...c, max_file_size_mb: Number(e.target.value) }))}
              />
            </label>
          </div>

          <label className="checkbox-line">
            <input type="checkbox" checked={form.is_active} onChange={(e) => setForm((c) => ({ ...c, is_active: e.target.checked }))} />
            Aktiv (öffentlich sichtbar)
          </label>

          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline">
              {editingId ? "Abgabe speichern" : "Abgabe erstellen"}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
