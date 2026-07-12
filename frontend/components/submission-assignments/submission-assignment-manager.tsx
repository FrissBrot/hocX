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
  submitted: "Abgegeben",
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
    return <div style={{ height: 3, borderRadius: 2, background: "var(--border)", marginTop: 6 }} />;
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
      <div style={{ marginTop: 6 }}>
        <div style={{ height: 3, borderRadius: 2, background: "var(--border)", overflow: "hidden", display: "flex", gap: 1 }}>
          {cleanPct > 0 && <div style={{ width: `${cleanPct}%`, background: "var(--success, #22c55e)", borderRadius: 2, flexShrink: 0 }} />}
          {qPct > 0 && <div style={{ width: `${qPct}%`, background: "var(--warning, #f59e0b)", borderRadius: 2, flexShrink: 0 }} />}
          {infPct > 0 && <div style={{ width: `${infPct}%`, background: "var(--danger, #ef4444)", borderRadius: 2, flexShrink: 0 }} />}
          {missingPct > 0 && <div style={{ width: `${missingPct}%`, borderRadius: 2, flexShrink: 0 }} />}
        </div>
        <span style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginTop: 3, display: "block" }}>
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
      <div style={{ marginTop: 6 }}>
        <div style={{ height: 3, borderRadius: 2, background: "var(--border)" }} />
        <span style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginTop: 3, display: "block" }}>Noch keine Abgaben</span>
      </div>
    );
  }
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ height: 3, borderRadius: 2, background: "var(--border)", overflow: "hidden", display: "flex", gap: 1 }}>
        {clean > 0 && <div style={{ flex: clean, background: "var(--success, #22c55e)", borderRadius: 2 }} />}
        {quarantine > 0 && <div style={{ flex: quarantine, background: "var(--warning, #f59e0b)", borderRadius: 2 }} />}
        {infected > 0 && <div style={{ flex: infected, background: "var(--danger, #ef4444)", borderRadius: 2 }} />}
      </div>
      <span style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginTop: 3, display: "block" }}>
        {total2} abgegeben
        {quarantine > 0 ? ` · ${quarantine} Quarantäne` : ""}
        {infected > 0 ? ` · ${infected} Schadware` : ""}
      </span>
    </div>
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
  const [hoveredRow, setHoveredRow] = useState<string | null>(null);
  const [hoveredAssignmentId, setHoveredAssignmentId] = useState<number | null>(null);
  const rescanTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [logModal, setLogModal] = useState<{ assignmentId: number; elementRef: string; label: string } | null>(null);
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

  async function openLog(assignmentId: number, elementRef: string, label: string) {
    setLogModal({ assignmentId, elementRef, label });
    setLogEntries([]);
    setLogLoading(true);
    try {
      const data = await browserApiFetch<SubmissionUploadLogEntry[]>(
        `/api/submission-assignments/${assignmentId}/upload-log?element_ref=${encodeURIComponent(elementRef)}`
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
      showToast("Element wieder aufgeschaltet", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Element konnte nicht wieder aufgeschaltet werden", "error");
    }
  }

  const selectedAssignment = assignments.find((a) => a.id === selectedId);
  const hasPendingFiles = elements.some((el) => el.files.some((f) => f.scan_status === "pending"));

  return (
    <div className="grid">
      {/* Toolbar — always visible, including ClamAV status */}
      <DataToolbar
        title="Abgaben"
        description="Externe Abgaben ohne Anmeldung — gekoppelt an Termine oder eine Liste."
        actions={
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <span style={{
                width: 7, height: 7, borderRadius: "50%", flexShrink: 0, display: "inline-block",
                background: clamavStatus === "online" ? "var(--success, #22c55e)" : clamavStatus === "offline" ? "var(--danger, #ef4444)" : "var(--border)",
              }} />
              <span style={{ fontSize: "0.78rem", color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                ClamAV {clamavStatus === "online" ? "Online" : clamavStatus === "offline" ? "Offline" : "…"}
              </span>
            </div>
            <button type="button" className="button-inline" onClick={openCreate}>
              Neue Abgabe
            </button>
          </div>
        }
      />

      {/* Split layout */}
      <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: 0, alignItems: "start" }}>

        {/* Left sidebar — assignment list */}
        <div style={{ borderRight: "1px solid var(--border)", paddingRight: 16, display: "flex", flexDirection: "column", minHeight: "calc(100vh - 180px)" }}>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Abgaben suchen…"
            style={{ padding: "7px 10px", borderRadius: 8, border: "1px solid var(--border)", backgroundColor: "transparent", color: "var(--text)", fontSize: "0.88rem", minHeight: 0, outline: "none", width: "100%", boxSizing: "border-box", marginBottom: 8 }}
          />

          <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 2 }}>
            {filteredAssignments.length === 0 ? (
              <span style={{ fontSize: "0.85rem", color: "var(--muted)", padding: "6px 4px", display: "block" }}>
                {assignments.length === 0 ? "Noch keine Abgaben" : "Keine Treffer"}
              </span>
            ) : filteredAssignments.map((assignment) => {
              const isSelected = selectedId === assignment.id;
              const isHovered = hoveredAssignmentId === assignment.id;
              return (
                <div
                  key={assignment.id}
                  style={{ position: "relative" }}
                  onMouseEnter={() => setHoveredAssignmentId(assignment.id)}
                  onMouseLeave={() => setHoveredAssignmentId(null)}
                >
                  <button
                    type="button"
                    onClick={() => void loadElements(assignment.id)}
                    style={{
                      display: "block",
                      width: "100%",
                      textAlign: "left",
                      padding: "9px 10px",
                      paddingRight: isHovered && !isSelected ? 64 : 10,
                      paddingBottom: 6,
                      borderRadius: 8,
                      border: "none",
                      background: isSelected ? "var(--accent)" : isHovered ? "color-mix(in srgb, var(--accent) 8%, transparent)" : "none",
                      color: isSelected ? "#fff" : "var(--text)",
                      cursor: "pointer",
                      minHeight: 0,
                      transition: "background 0.12s",
                    }}
                  >
                    <div style={{ fontSize: "0.9rem", fontWeight: isSelected ? 600 : 500, lineHeight: 1.3 }}>
                      {assignment.title}
                    </div>
                    <div style={{ marginTop: 2, display: "flex", gap: 5, alignItems: "center" }}>
                      <span style={{
                        fontSize: "0.68rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em",
                        color: isSelected ? "rgba(255,255,255,0.7)" : "var(--text-muted)",
                      }}>
                        {assignment.source_type === "events" ? "Termine" : "Liste"}
                      </span>
                      {!assignment.is_active && (
                        <span style={{
                          fontSize: "0.65rem", fontWeight: 600, textTransform: "uppercase",
                          color: isSelected ? "rgba(255,255,255,0.6)" : "var(--text-muted)",
                        }}>
                          · Inaktiv
                        </span>
                      )}
                    </div>
                    <div style={{ opacity: isSelected ? 0.85 : 1 }}>
                      <SummaryBar summary={summaries[assignment.id]} />
                    </div>
                  </button>

                  {isHovered && !isSelected && (
                    <div style={{ position: "absolute", top: "50%", right: 4, transform: "translateY(-50%)", display: "flex", gap: 2, zIndex: 1 }}>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); openEdit(assignment); }}
                        style={{ padding: "3px 6px", background: "var(--panel-solid)", border: "1px solid var(--border)", borderRadius: 5, cursor: "pointer", color: "var(--text)", fontSize: "0.72rem", minHeight: 0, lineHeight: 1 }}
                      >
                        ✎
                      </button>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); void deleteAssignment(assignment.id); }}
                        style={{ padding: "3px 6px", background: "var(--panel-solid)", border: "1px solid var(--border)", borderRadius: 5, cursor: "pointer", color: "var(--danger)", fontSize: "0.72rem", minHeight: 0, lineHeight: 1 }}
                      >
                        ×
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Right panel — elements */}
        <div style={{ paddingLeft: 20, minWidth: 0 }}>
          {selectedId === null ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: 240, color: "var(--text-muted)", fontSize: "0.9rem" }}>
              Abgabe auswählen
            </div>
          ) : (
            <>
              {/* Panel header */}
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 14 }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span className="eyebrow" style={{ margin: 0 }}>{selectedAssignment?.title}</span>
                    {hasPendingFiles && (
                      <span className="pill pill-sm pill-warning" style={{ animation: "pulse 2s infinite" }}>
                        Dateien in Quarantäne
                      </span>
                    )}
                  </div>
                </div>
                <button
                  type="button"
                  className={`pdf-icon-link pdf-icon-link-success${zipLoading ? " pdf-icon-disabled" : ""}`}
                  onClick={() => void downloadZip(selectedId)}
                  disabled={zipLoading}
                  title="Alle geprüften Dateien als ZIP herunterladen"
                  style={{ flexShrink: 0, width: "auto", minWidth: 56, minHeight: 0, padding: "0 14px", display: "inline-flex", alignItems: "center", justifyContent: "center" }}
                >
                  {zipLoading ? "…" : "ZIP"}
                </button>
              </div>

              {/* Elements table */}
              {elementsLoading ? (
                <p className="muted">Lädt…</p>
              ) : elements.length === 0 ? (
                <p className="muted">Keine Elemente gefunden.</p>
              ) : (
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.88rem" }}>
                    <thead>
                      <tr>
                        {["Element", "Verantwortlich", "Fenster/Frist", "Status", "Dateien", "Aktion"].map((col) => (
                          <th key={col} style={{ textAlign: "left", padding: "6px 10px", borderBottom: "2px solid var(--border)", color: "var(--text-muted)", fontWeight: 600, fontSize: "0.78rem", textTransform: "uppercase", letterSpacing: "0.04em", whiteSpace: "nowrap" }}>
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {elements.map((element) => {
                        const isHov = hoveredRow === element.element_ref;
                        return (
                          <tr
                            key={element.element_ref}
                            onMouseEnter={() => setHoveredRow(element.element_ref)}
                            onMouseLeave={() => setHoveredRow(null)}
                            style={{ background: isHov ? "color-mix(in srgb, var(--accent, #6366f1) 5%, transparent)" : "transparent", transition: "background 0.1s" }}
                          >
                            <td style={{ padding: "8px 10px", borderBottom: "1px solid var(--border)" }}>
                              <strong style={{ fontWeight: 500 }}>{element.label}</strong>
                            </td>
                            <td style={{ padding: "8px 10px", borderBottom: "1px solid var(--border)", color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                              {element.responsible_participant_id
                                ? (availableParticipants.find((p) => p.id === element.responsible_participant_id)?.display_name ?? `#${element.responsible_participant_id}`)
                                : "—"}
                            </td>
                            <td style={{ padding: "8px 10px", borderBottom: "1px solid var(--border)", color: "var(--text-muted)", whiteSpace: "nowrap", fontSize: "0.82rem" }}>
                              {element.window_start && element.window_end
                                ? `${element.window_start} – ${element.window_end}`
                                : element.window_end ?? "—"}
                            </td>
                            <td style={{ padding: "8px 10px", borderBottom: "1px solid var(--border)", whiteSpace: "nowrap" }}>
                              {statusClass(element) ? (
                                <span className={`pill pill-sm ${statusClass(element)}`}>{statusLabel(element)}</span>
                              ) : (
                                <span style={{ color: "var(--text-muted)", fontSize: "0.82rem" }}>{statusLabel(element)}</span>
                              )}
                            </td>
                            <td style={{ padding: "8px 10px", borderBottom: "1px solid var(--border)" }}>
                              {element.files.length === 0
                                ? <span style={{ color: "var(--text-muted)" }}>—</span>
                                : element.files.map((file) => (
                                    <div key={file.id} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                                      {file.scan_status === "clean" ? (
                                        <a href={file.content_url} target="_blank" rel="noreferrer" style={{ fontSize: "0.85rem" }}>
                                          {file.original_name}
                                        </a>
                                      ) : (
                                        <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>{file.original_name}</span>
                                      )}
                                      <span className={`pill pill-sm ${SCAN_STATUS_CLASS[file.scan_status] ?? ""}`}>
                                        {SCAN_STATUS_LABEL[file.scan_status] ?? file.scan_status}
                                      </span>
                                    </div>
                                  ))}
                            </td>
                            <td style={{ padding: "8px 10px", borderBottom: "1px solid var(--border)", whiteSpace: "nowrap" }}>
                              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                                {element.status === "submitted" ? (
                                  <button
                                    type="button"
                                    className="button-inline"
                                    style={{ fontSize: "0.78rem", padding: "3px 9px" }}
                                    onClick={() => void reopenElement(selectedId, element.element_ref)}
                                  >
                                    Wieder aufschalten
                                  </button>
                                ) : null}
                                <button
                                  type="button"
                                  className="button-inline button-ghost"
                                  style={{ fontSize: "0.78rem", padding: "3px 9px" }}
                                  onClick={() => void openLog(selectedId, element.element_ref, element.label)}
                                >
                                  Log
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Upload-Log Modal */}
      <Modal
        open={logModal !== null}
        onClose={() => setLogModal(null)}
        title={`Upload-Log — ${logModal?.label ?? ""}`}
      >
        <div style={{ minWidth: 480, maxWidth: 640 }}>
          {logLoading ? (
            <p className="muted">Lädt…</p>
          ) : logEntries.length === 0 ? (
            <p className="muted">Keine Einträge vorhanden.</p>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", padding: "4px 8px", borderBottom: "1px solid var(--border)", color: "var(--text-muted)", fontWeight: 600 }}>Zeitpunkt</th>
                  <th style={{ textAlign: "left", padding: "4px 8px", borderBottom: "1px solid var(--border)", color: "var(--text-muted)", fontWeight: 600 }}>Status</th>
                  <th style={{ textAlign: "left", padding: "4px 8px", borderBottom: "1px solid var(--border)", color: "var(--text-muted)", fontWeight: 600 }}>Details</th>
                </tr>
              </thead>
              <tbody>
                {logEntries.map((entry) => (
                  <tr key={entry.id}>
                    <td style={{ padding: "6px 8px", borderBottom: "1px solid var(--border)", whiteSpace: "nowrap", color: "var(--text-muted)" }}>
                      {new Date(entry.created_at).toLocaleString("de-CH")}
                    </td>
                    <td style={{ padding: "6px 8px", borderBottom: "1px solid var(--border)" }}>
                      <span className={`pill pill-sm ${LOG_STATUS_CLASS[entry.status] ?? ""}`}>
                        {LOG_STATUS_LABEL[entry.status] ?? entry.status}
                      </span>
                    </td>
                    <td style={{ padding: "6px 8px", borderBottom: "1px solid var(--border)", color: "var(--text-muted)" }}>
                      {entry.error_message ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
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
