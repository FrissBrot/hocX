"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import {
  AssignmentSummary,
  EventSummary,
  ParticipantSummary,
  StructuredListDefinition,
  SubmissionAssignment,
  SubmissionElementStatusEntry,
  SubmissionSortOrder,
  SubmissionSourceType,
  SubmissionUploadLogEntry,
} from "@/types/api";

const SORT_ORDER_LABEL: Record<SubmissionSortOrder, string> = {
  alphabetical: "Alphabetisch",
  date: "Nach Datum",
  proximity: "Nähe zu heute",
};

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
  max_files_per_element: number | "";
  max_file_size_mb: number;
  sort_order: SubmissionSortOrder;
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
  max_files_per_element: 5,
  max_file_size_mb: 20,
  sort_order: "date",
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
    max_files_per_element: assignment.max_files_per_element ?? "",
    max_file_size_mb: assignment.max_file_size_mb,
    sort_order: assignment.sort_order,
    responsible_participant_source: assignment.responsible_participant_source ?? "",
  };
}

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

export function SubmissionAssignmentManager({ initialAssignments, availableLists, availableEvents, availableParticipants }: Props) {
  const showToast = useToast();
  const confirm = useConfirm();
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
            offset_days_before: form.offset_days_before === "" ? null : Number(form.offset_days_before),
            offset_days_after: form.offset_days_after === "" ? null : Number(form.offset_days_after),
            list_definition_id: null,
            deadline: null,
            allowed_file_types: form.allowed_file_types,
            max_files_per_element: form.max_files_per_element === "" ? null : Number(form.max_files_per_element),
            max_file_size_mb: Number(form.max_file_size_mb),
            sort_order: form.sort_order,
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
            deadline: form.deadline || null,
            allowed_file_types: form.allowed_file_types,
            max_files_per_element: form.max_files_per_element === "" ? null : Number(form.max_files_per_element),
            max_file_size_mb: Number(form.max_file_size_mb),
            sort_order: form.sort_order,
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

  async function closeElement(assignmentId: number, elementRef: string) {
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
      const source = assignment.tag_filter ? `Termin „${assignment.tag_filter}“` : "Termine";
      const before = assignment.offset_days_before;
      const after = assignment.offset_days_after;
      const windowParts = [
        before !== null ? `ab ${before} Tage vorher` : null,
        after !== null ? `bis ${after} Tage danach` : null,
      ].filter((v): v is string => Boolean(v));
      const window = windowParts.length > 0 ? windowParts.join(", ") : "kein Zeitfenster (offen bis manuell geschlossen)";
      return `Quelle: ${source} · ${window}`;
    }
    const list = availableLists.find((l) => l.id === assignment.list_definition_id);
    const source = list ? `Liste „${list.name}“` : "Liste";
    const deadline = assignment.deadline ? `Deadline ${formatDateShort(assignment.deadline)}` : "Kein Stichtag (offen bis manuell geschlossen)";
    return `Quelle: ${source} · ${deadline}`;
  }

  return (
    <div className="grid subm-root">
      {/* Header — always visible, including ClamAV status */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Abgaben</h1>
          <p className="muted">Externe Abgaben ohne Anmeldung — gekoppelt an Termine oder eine Liste.</p>
        </div>
        <div className="subm-toolbar-actions">
          <span className={`subm-clamav subm-clamav-${clamavStatus}`}>
            <span className="subm-clamav-dot" />
            ClamAV {clamavStatus === "online" ? "Online" : clamavStatus === "offline" ? "Offline" : "…"}
          </span>
          <button type="button" className="button-inline subm-new-button" onClick={openCreate}>
            <PlusIcon /> Abgabe
          </button>
        </div>
      </div>

      <div className="list-filter-row">
        <div />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder="Abgaben suchen…" />
        </div>
      </div>

      {/* Assignment list */}
      {filteredAssignments.length === 0 ? (
        <p className="muted record-list-empty">
          {assignments.length === 0 ? "Noch keine Abgaben" : "Keine Treffer"}
        </p>
      ) : (
        <div className="record-list">
          {filteredAssignments.map((assignment) => (
            <div
              key={assignment.id}
              className="record-list-row"
              onClick={() => void loadElements(assignment.id)}
            >
              <span className="record-list-row-text">
                <span className="record-list-row-title">{assignment.title}</span>
                <span className="record-list-row-sub">{metaLine(assignment)}</span>
              </span>
              <div className="record-list-row-trailing">
                <SummaryBar summary={summaries[assignment.id]} />
                <div className="subm-row-actions">
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
              </div>
            </div>
          ))}
        </div>
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

            <div className="subm-modal-section-title">Teilnehmer</div>

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
                    ? (availableParticipants.find((p) => p.id === element.responsible_participant_id)?.display_name ?? `#${element.responsible_participant_id}`)
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
                className="button-ghost button-inline"
                onClick={() => void downloadZip(selectedId)}
                disabled={zipLoading}
                title="Alle geprüften Dateien als ZIP herunterladen"
              >
                <DownloadIcon /> {zipLoading ? "…" : "Alle Dateien (.zip)"}
              </button>
              <button type="button" className="button-inline" onClick={() => setSelectedId(null)}>
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
                  className="button-ghost button-inline subm-reopen-button"
                  onClick={() => selectedId && void reopenElement(selectedId, elementModal.element_ref)}
                >
                  Wieder aufschalten
                </button>
              ) : (
                <button
                  type="button"
                  className="button-ghost button-inline subm-close-button"
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
                          style={{ width: "100%", boxSizing: "border-box", padding: "6px 10px", borderRadius: 6, border: "1px solid var(--border)", backgroundColor: "var(--bg)", color: "var(--text)", fontSize: "0.88rem", minHeight: 0, outline: "none" }}
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
                    placeholder="unbegrenzt"
                    value={form.offset_days_before}
                    onChange={(e) => setForm((c) => ({ ...c, offset_days_before: e.target.value === "" ? "" : Number(e.target.value) }))}
                  />
                </label>
                <label className="field-stack">
                  <span className="field-label">Tage nach Termin (bis)</span>
                  <input
                    type="number"
                    min={0}
                    placeholder="unbegrenzt"
                    value={form.offset_days_after}
                    onChange={(e) => setForm((c) => ({ ...c, offset_days_after: e.target.value === "" ? "" : Number(e.target.value) }))}
                  />
                </label>
              </div>
              <span className="field-help">
                Leer lassen = kein Zeitfenster auf dieser Seite. Ohne beide Werte bleibt die Abgabe offen, bis sie manuell geschlossen wird.
              </span>
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
                />
                <span className="field-help">Leer lassen = kein Stichtag, Abgabe bleibt offen, bis sie manuell geschlossen wird.</span>
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
                placeholder="unbegrenzt"
                value={form.max_files_per_element}
                onChange={(e) => setForm((c) => ({ ...c, max_files_per_element: e.target.value === "" ? "" : Number(e.target.value) }))}
              />
              <span className="field-help">Leer lassen = unbegrenzt viele Dateien.</span>
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

          <label className="field-stack">
            <span className="field-label">Sortierung der Elemente</span>
            <select
              value={form.sort_order}
              onChange={(e) => setForm((c) => ({ ...c, sort_order: e.target.value as SubmissionSortOrder }))}
            >
              {(Object.keys(SORT_ORDER_LABEL) as SubmissionSortOrder[]).map((value) => (
                <option key={value} value={value}>
                  {SORT_ORDER_LABEL[value]}
                </option>
              ))}
            </select>
            <span className="field-help">Wird unverändert in der öffentlichen Abgabebox übernommen (dort nicht anpassbar).</span>
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
