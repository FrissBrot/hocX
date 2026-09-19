"use client";

import { useEffect, useState } from "react";

import { SearchableSelect } from "@/components/ui/searchable-select";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate } from "@/lib/utils/format";
import { CycleConfigSummary, EventSummary, SubmissionAssignment, SubmissionElementStatusEntry } from "@/types/api";

type TargetCategory = "none" | "event" | "submission_element" | "cycle";

// The file rules of the chosen Abgabe (SubmissionAssignment.allowed_file_types/max_file_size_mb/
// max_files_per_element). The backend enforces them again on every upload
// (submission_upload_rules.py) - this copy only lets the window explain a problem up front.
export type UploadRules = {
  allowedExtensions: string[]; // lower-case, no dot; empty = any type
  maxFileSizeMb: number;
  maxFiles: number | null;
};

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot + 1).toLowerCase();
}

// `zipIsContainer`: the photo window accepts .zip only as a carrier for images, so the ZIP
// itself is exempt from the type/size rules (the backend judges each entry once it opens it).
export function findUploadRuleProblems(files: File[], rules: UploadRules | null, zipIsContainer = false): string[] {
  if (!rules) return [];
  const problems: string[] = [];
  const judged = files.filter((file) => !(zipIsContainer && extensionOf(file.name) === "zip"));
  for (const file of judged) {
    const extension = extensionOf(file.name);
    if (rules.allowedExtensions.length > 0 && !rules.allowedExtensions.includes(extension)) {
      problems.push(`${file.name}: Dateityp '.${extension}' nicht erlaubt`);
    } else if (file.size > rules.maxFileSizeMb * 1024 * 1024) {
      problems.push(`${file.name}: zu gross (max. ${rules.maxFileSizeMb} MB)`);
    }
  }
  if (rules.maxFiles !== null && judged.length > rules.maxFiles) {
    problems.push(`Maximal ${rules.maxFiles} Dateien pro Element erlaubt (${judged.length} gewählt)`);
  }
  return problems;
}

const TARGET_CATEGORY_OPTIONS: { id: TargetCategory; label: string }[] = [
  { id: "none", label: "Kein Bezug" },
  { id: "event", label: "Termin" },
  { id: "submission_element", label: "Abgabe-Element" },
  { id: "cycle", label: "Zyklus" },
];

// State behind the optional "Bezug" picker of an upload window (Kein Bezug / Termin / Abgabe-
// Element / Zyklus) - the same choice, and the same form fields, POST /files/gallery-uploads
// and POST /files/document-uploads both take. Kept separate from <UploadTargetFields> so the
// window itself can read `incomplete` (to disable its submit button) and call `appendTo`
// when it builds its FormData.
export function useUploadTarget() {
  const [targetKind, setTargetKind] = useState<TargetCategory>("none");
  const [events, setEvents] = useState<EventSummary[]>([]);
  const [assignments, setAssignments] = useState<SubmissionAssignment[]>([]);
  const [cycleConfigs, setCycleConfigs] = useState<CycleConfigSummary[]>([]);
  const [elements, setElements] = useState<SubmissionElementStatusEntry[]>([]);
  const [selectedEventId, setSelectedEventId] = useState("");
  const [selectedAssignmentId, setSelectedAssignmentId] = useState("");
  const [selectedElementRef, setSelectedElementRef] = useState("");
  const [selectedCycleConfigId, setSelectedCycleConfigId] = useState("");

  useEffect(() => {
    browserApiFetch<EventSummary[]>("/api/events").then((data) => setEvents(data ?? [])).catch(() => {});
    browserApiFetch<SubmissionAssignment[]>("/api/submission-assignments").then((data) => setAssignments(data ?? [])).catch(() => {});
    browserApiFetch<CycleConfigSummary[]>("/api/cycle-configs").then((data) => setCycleConfigs(data ?? [])).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedAssignmentId) {
      setElements([]);
      return;
    }
    browserApiFetch<SubmissionElementStatusEntry[]>(`/api/submission-assignments/${selectedAssignmentId}/elements`)
      .then((data) => setElements(data ?? []))
      .catch(() => setElements([]));
  }, [selectedAssignmentId]);

  // Only an Abgabe-Element Bezug brings file rules along.
  const selectedAssignment = targetKind === "submission_element" ? assignments.find((a) => a.id === selectedAssignmentId) : undefined;
  const rules: UploadRules | null = selectedAssignment
    ? {
        allowedExtensions: selectedAssignment.allowed_file_types.map((type) => type.toLowerCase().replace(/^\./, "")),
        maxFileSizeMb: selectedAssignment.max_file_size_mb,
        maxFiles: selectedAssignment.max_files_per_element,
      }
    : null;

  const incomplete =
    (targetKind === "event" && !selectedEventId) ||
    (targetKind === "submission_element" && (!selectedAssignmentId || !selectedElementRef)) ||
    (targetKind === "cycle" && !selectedCycleConfigId);

  function appendTo(body: FormData) {
    if (targetKind === "event") body.append("event_id", selectedEventId);
    if (targetKind === "submission_element") {
      body.append("submission_assignment_id", selectedAssignmentId);
      body.append("submission_element_ref", selectedElementRef);
    }
    if (targetKind === "cycle") body.append("cycle_config_id", selectedCycleConfigId);
  }

  return {
    targetKind,
    setTargetKind,
    events,
    assignments,
    cycleConfigs,
    elements,
    selectedEventId,
    setSelectedEventId,
    selectedAssignmentId,
    setSelectedAssignmentId,
    selectedElementRef,
    setSelectedElementRef,
    selectedCycleConfigId,
    setSelectedCycleConfigId,
    rules,
    incomplete,
    appendTo,
  };
}

export function UploadTargetFields({ target }: { target: ReturnType<typeof useUploadTarget> }) {
  return (
    <>
      <div className="gallery-upload-fields">
        <label>
          Bezug
          <SearchableSelect
            options={TARGET_CATEGORY_OPTIONS}
            getId={(option) => option.id}
            getLabel={(option) => option.label}
            value={target.targetKind}
            onChange={(option) => target.setTargetKind(option?.id ?? "none")}
          />
        </label>
        {target.targetKind === "event" && (
          <label>
            Termin
            <SearchableSelect
              options={target.events}
              getId={(event) => event.id}
              getLabel={(event) => `${event.title} (${formatDate(event.event_date)})`}
              value={target.selectedEventId || null}
              onChange={(event) => target.setSelectedEventId(event?.id ?? "")}
              placeholder="Termin wählen…"
            />
          </label>
        )}
        {target.targetKind === "submission_element" && (
          <label>
            Abgabe
            <SearchableSelect
              options={target.assignments}
              getId={(assignment) => assignment.id}
              getLabel={(assignment) => assignment.title}
              value={target.selectedAssignmentId || null}
              onChange={(assignment) => {
                target.setSelectedAssignmentId(assignment?.id ?? "");
                target.setSelectedElementRef("");
              }}
              placeholder="Abgabe wählen…"
            />
          </label>
        )}
        {target.targetKind === "cycle" && (
          <label>
            Zyklus
            <SearchableSelect
              options={target.cycleConfigs}
              getId={(cycleConfig) => cycleConfig.id}
              getLabel={(cycleConfig) => cycleConfig.name}
              value={target.selectedCycleConfigId || null}
              onChange={(cycleConfig) => target.setSelectedCycleConfigId(cycleConfig?.id ?? "")}
              placeholder="Zyklus wählen…"
            />
          </label>
        )}
      </div>
      {target.rules && (
        <p className="muted" data-testid="upload-rules">
          Regeln der Abgabe:{" "}
          {target.rules.allowedExtensions.length > 0
            ? `nur ${target.rules.allowedExtensions.map((type) => type.toUpperCase()).join(", ")}`
            : "alle Dateitypen"}
          {` · max. ${target.rules.maxFileSizeMb} MB pro Datei`}
          {target.rules.maxFiles !== null ? ` · max. ${target.rules.maxFiles} Dateien pro Element` : ""}
        </p>
      )}
      {target.targetKind === "submission_element" && target.selectedAssignmentId && (
        <label className="gallery-upload-tags">
          <span className="gallery-upload-label">Abgabe-Element</span>
          <SearchableSelect
            options={target.elements}
            getId={(element) => element.element_ref}
            getLabel={(element) => element.label}
            value={target.selectedElementRef || null}
            onChange={(element) => target.setSelectedElementRef(element?.element_ref ?? "")}
            placeholder="Element wählen…"
          />
        </label>
      )}
    </>
  );
}
