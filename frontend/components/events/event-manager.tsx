"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useTableSort } from "@/lib/hooks/use-table-sort";
import { formatDate, formatDateRange } from "@/lib/utils/format";
import { CycleAssignment, CycleInfo, DocumentTemplate, EventSummary, ParticipantSummary, TemplateSummary } from "@/types/api";

const PAGE_SIZE = 100;

type Props = {
  initialEvents: EventSummary[];
  documentTemplates?: DocumentTemplate[];
  availableParticipants?: ParticipantSummary[];
};

type ParticipantPickerField = "organizer_ids" | "leadership_ids" | "participant_ids" | "spezial1_ids" | "spezial2_ids" | "spezial3_ids";

const PARTICIPANT_ROLE_FIELDS: { field: ParticipantPickerField; label: string }[] = [
  { field: "organizer_ids", label: "Organisatoren" },
  { field: "leadership_ids", label: "Leitungsteam" },
  { field: "participant_ids", label: "Teilnehmer" },
  { field: "spezial1_ids", label: "Spezial 1" },
  { field: "spezial2_ids", label: "Spezial 2" },
  { field: "spezial3_ids", label: "Spezial 3" },
];

type FlatCycle = CycleInfo & { cycle_config_id: number; config_name: string };

type EventFormState = {
  id?: number;
  event_date: string;
  event_end_date: string;
  tag: string;
  title: string;
  description: string;
  participant_count: string;
  cycle_assignments: CycleAssignment[];
  organizer_ids: number[];
  leadership_ids: number[];
  participant_ids: number[];
  spezial1_ids: number[];
  spezial2_ids: number[];
  spezial3_ids: number[];
  location: string;
  spezial_text1: string;
  spezial_text2: string;
  spezial_text3: string;
};

function emptyForm(): EventFormState {
  return {
    event_date: new Date().toISOString().slice(0, 10),
    event_end_date: "",
    tag: "",
    title: "",
    description: "",
    participant_count: "0",
    cycle_assignments: [],
    organizer_ids: [],
    leadership_ids: [],
    participant_ids: [],
    spezial1_ids: [],
    spezial2_ids: [],
    spezial3_ids: [],
    location: "",
    spezial_text1: "",
    spezial_text2: "",
    spezial_text3: "",
  };
}

export function EventManager({ initialEvents, documentTemplates = [], availableParticipants = [] }: Props) {
  const showToast = useToast();
  const [events, setEvents] = useState(initialEvents);
  const [hasMore, setHasMore] = useState(initialEvents.length === PAGE_SIZE);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [search, setSearch] = useState("");
  const [tagFilter, setTagFilter] = useState("all");
  const { sortKey, sortDirection, toggleSort, sortIndicator } = useTableSort<"event_date" | "title" | "tag" | "description" | "participant_count">("event_date");
  const [showParticipantCount, setShowParticipantCount] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<EventFormState>(emptyForm);
  const [todayIso, setTodayIso] = useState("0000-01-01");
  const [availableCycles, setAvailableCycles] = useState<FlatCycle[]>([]);
  const [cyclesLoading, setCyclesLoading] = useState(false);
  const cyclesLoadedRef = useRef(false);

  const [pickerField, setPickerField] = useState<ParticipantPickerField | null>(null);
  const [pickerSelected, setPickerSelected] = useState<number[]>([]);
  const [pickerSearch, setPickerSearch] = useState("");

  const landscapeTemplates = documentTemplates.filter(
    (t) => t.is_active && (t.configuration_json as { options?: { orientation?: string } })?.options?.orientation === "landscape"
  );

  // Export modal state
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [exportTemplateId, setExportTemplateId] = useState<number | "">(landscapeTemplates[0]?.id ?? "");
  const [exportBusy, setExportBusy] = useState(false);
  const [exportUrl, setExportUrl] = useState<string | null>(null);
  const [templateDropdownOpen, setTemplateDropdownOpen] = useState(false);
  const templateDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!templateDropdownOpen) return;
    function handleClick(e: MouseEvent) {
      if (templateDropdownRef.current && !templateDropdownRef.current.contains(e.target as Node)) {
        setTemplateDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [templateDropdownOpen]);
  const [exportTagFilters, setExportTagFilters] = useState<string[]>([]);
  const [exportTagSearch, setExportTagSearch] = useState("");
  const [exportDateMode, setExportDateMode] = useState<"all" | "next-session" | "until-event">("all");
  const [exportUntilEventId, setExportUntilEventId] = useState<number | "">("");

  const knownExportTags = useMemo(() => {
    const set = new Set<string>();
    events.forEach((e) => { if (e.tag) set.add(e.tag); });
    return Array.from(set).sort();
  }, [events]);

  const tagSuggestions = useMemo(() => {
    if (!exportTagSearch.trim()) return [];
    const q = exportTagSearch.toLowerCase();
    return knownExportTags.filter((t) => t.toLowerCase().includes(q) && !exportTagFilters.includes(t));
  }, [exportTagSearch, knownExportTags, exportTagFilters]);

  const nextSessionEvent = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    return events.find((e) => e.event_date >= today && e.tag?.toLowerCase().includes("sitzung")) ?? null;
  }, [events]);

  const sortedEvents = useMemo(() => [...events].sort((a, b) => a.event_date.localeCompare(b.event_date)), [events]);

  function toggleExportTag(tag: string) {
    setExportTagFilters((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    );
    setExportUrl(null);
  }

  function getUntilDate(): string | null {
    if (exportDateMode === "all") return null;
    if (exportDateMode === "next-session") return nextSessionEvent?.event_date ?? null;
    if (exportDateMode === "until-event" && exportUntilEventId) {
      const ev = events.find((e) => e.id === exportUntilEventId);
      return ev?.event_date ?? null;
    }
    return null;
  }

  function triggerDownload(url: string) {
    const a = document.createElement("a");
    a.href = `${url}?download=1`;
    a.target = "_blank";
    a.rel = "noreferrer";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  async function handlePdfClick() {
    if (exportBusy) return;
    if (exportUrl) { triggerDownload(exportUrl); return; }
    if (!exportTemplateId) return;
    setExportBusy(true);
    try {
      const result = await browserApiFetch<{ content_url?: string | null }>("/api/exports/events", {
        method: "POST",
        body: JSON.stringify({
          template_id: exportTemplateId,
          tag_filters: exportTagFilters,
          until_date: getUntilDate(),
        }),
      });
      const url = result.content_url ?? null;
      setExportUrl(url);
      if (url) triggerDownload(url);
    } catch {
      // keep button accessible on error
    } finally {
      setExportBusy(false);
    }
  }

  useEffect(() => {
    setTodayIso(new Date().toISOString().slice(0, 10));
  }, []);

  async function ensureCyclesLoaded() {
    if (cyclesLoadedRef.current) return;
    cyclesLoadedRef.current = true;
    setCyclesLoading(true);
    try {
      const configs = await browserApiFetch<import("@/types/api").CycleConfigSummary[]>("/api/cycle-configs");
      const cycleGroups = await Promise.all(
        (configs ?? []).map((cfg) =>
          browserApiFetch<CycleInfo[]>(`/api/cycle-configs/${cfg.id}/cycles`).then((cycles) =>
            (cycles ?? []).map((c) => ({ ...c, cycle_config_id: cfg.id, config_name: cfg.name }))
          ).catch(() => [] as FlatCycle[])
        )
      );
      setAvailableCycles(cycleGroups.flat());
    } catch {
      cyclesLoadedRef.current = false;
    } finally {
      setCyclesLoading(false);
    }
  }

  const knownTags = useMemo(
    () =>
      Array.from(
        new Set(
          events
            .map((event) => (event.tag ?? "").trim())
            .filter((tag) => tag.length > 0)
        )
      ).sort((left, right) => left.localeCompare(right)),
    [events]
  );
  const filteredEvents = useMemo(() => {
    const query = search.trim().toLowerCase();
    const includePast = query.length > 0;
    return [...events]
      .filter((event) => {
        if (!includePast) {
          const effectiveEndDate = event.event_end_date || event.event_date;
          if (effectiveEndDate < todayIso) {
            return false;
          }
        }
        if (tagFilter !== "all" && (event.tag ?? "") !== tagFilter) {
          return false;
        }
        if (!query) {
          return true;
        }
        const haystack = `${event.title} ${event.tag ?? ""} ${event.description ?? ""}`.toLowerCase();
        return haystack.includes(query);
      })
      .sort((left, right) => {
        const direction = sortDirection === "asc" ? 1 : -1;
        if (sortKey === "event_date") {
          const leftValue = left.event_date;
          const rightValue = right.event_date;
          return leftValue.localeCompare(rightValue) * direction;
        }
        if (sortKey === "participant_count") {
          return ((left.participant_count ?? 0) - (right.participant_count ?? 0)) * direction;
        }
        const leftValue = String(left[sortKey] ?? "").toLowerCase();
        const rightValue = String(right[sortKey] ?? "").toLowerCase();
        return leftValue.localeCompare(rightValue) * direction;
      });
  }, [events, search, sortDirection, sortKey, tagFilter, todayIso]);

  function openCreate() {
    setForm(emptyForm());
    void ensureCyclesLoaded();
    setModalOpen(true);
  }

  function openEdit(event: EventSummary) {
    setForm({
      id: event.id,
      event_date: event.event_date,
      event_end_date: event.event_end_date ?? "",
      tag: event.tag ?? "",
      title: event.title,
      description: event.description ?? "",
      participant_count: String(event.participant_count ?? 0),
      cycle_assignments: event.cycle_assignments ?? [],
      organizer_ids: event.organizer_ids ?? [],
      leadership_ids: event.leadership_ids ?? [],
      participant_ids: event.participant_ids ?? [],
      spezial1_ids: event.spezial1_ids ?? [],
      spezial2_ids: event.spezial2_ids ?? [],
      spezial3_ids: event.spezial3_ids ?? [],
      location: event.location ?? "",
      spezial_text1: event.spezial_text1 ?? "",
      spezial_text2: event.spezial_text2 ?? "",
      spezial_text3: event.spezial_text3 ?? "",
    });
    void ensureCyclesLoaded();
    setModalOpen(true);
  }

  function openParticipantPicker(field: ParticipantPickerField) {
    setPickerField(field);
    setPickerSelected([...(form[field] as number[])]);
    setPickerSearch("");
  }

  function applyParticipantPicker() {
    if (!pickerField) return;
    setForm((current) => ({ ...current, [pickerField]: pickerSelected }));
    setPickerField(null);
  }

  function participantLabel(ids: number[]): string {
    if (!ids.length) return "Auswählen…";
    const names = ids
      .map((id) => availableParticipants.find((p) => p.id === id)?.display_name)
      .filter(Boolean);
    return names.length ? names.join(", ") : `${ids.length} ausgewählt`;
  }

  function toggleCycle(cycleConfigId: number, cycleYear: number) {
    setForm((current) => {
      const exists = current.cycle_assignments.some(
        (a) => a.cycle_config_id === cycleConfigId && a.cycle_year === cycleYear
      );
      const next = exists
        ? current.cycle_assignments.filter((a) => !(a.cycle_config_id === cycleConfigId && a.cycle_year === cycleYear))
        : [...current.cycle_assignments, { cycle_config_id: cycleConfigId, cycle_year: cycleYear }];
      return { ...current, cycle_assignments: next };
    });
  }

  async function saveEvent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const payload = {
        event_date: form.event_date,
        event_end_date: form.event_end_date || null,
        tag: form.tag || null,
        title: form.title,
        description: form.description || null,
        participant_count: Math.max(0, Number(form.participant_count || "0")),
        cycle_assignments: form.cycle_assignments,
        organizer_ids: form.organizer_ids,
        leadership_ids: form.leadership_ids,
        participant_ids: form.participant_ids,
        spezial1_ids: form.spezial1_ids,
        spezial2_ids: form.spezial2_ids,
        spezial3_ids: form.spezial3_ids,
        location: form.location || null,
        spezial_text1: form.spezial_text1 || null,
        spezial_text2: form.spezial_text2 || null,
        spezial_text3: form.spezial_text3 || null,
      };
      const saved = form.id
        ? await browserApiFetch<EventSummary>(`/api/events/${form.id}`, {
            method: "PATCH",
            body: JSON.stringify(payload),
          })
        : await browserApiFetch<EventSummary>("/api/events", {
            method: "POST",
            body: JSON.stringify(payload),
          });

      setEvents((current) =>
        form.id ? current.map((item) => (item.id === saved.id ? saved : item)) : [saved, ...current]
      );
      setModalOpen(false);
      showToast(form.id ? "Termin gespeichert" : "Termin erstellt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Termin konnte nicht gespeichert werden", "error");
    }
  }

  async function deleteEvent(eventId: number) {
    try {
      await browserApiFetch(`/api/events/${eventId}`, { method: "DELETE" });
      setEvents((current) => current.filter((event) => event.id !== eventId));
      showToast("Termin gelöscht", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Termin konnte nicht gelöscht werden", "error");
    }
  }

  async function loadMore() {
    setIsLoadingMore(true);
    try {
      const next = await browserApiFetch<EventSummary[]>(`/api/events?skip=${events.length}&limit=${PAGE_SIZE}`);
      setEvents((current) => [...current, ...next]);
      setHasMore(next.length === PAGE_SIZE);
    } catch {
      // keep current list on error
    } finally {
      setIsLoadingMore(false);
    }
  }

  async function importCsv(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    try {
      const body = new FormData();
      body.append("file", file);
      const imported = await browserApiFetch<EventSummary[]>("/api/events/import-csv", {
        method: "POST",
        body,
      });
      setEvents((current) => [...imported, ...current]);
      showToast(`${imported.length} Termine importiert`, "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "CSV-Import fehlgeschlagen", "error");
    } finally {
      event.target.value = "";
    }
  }

  return (
    <div className="grid">
      <DataToolbar
        title="Termine"
        actions={
          <div className="table-toolbar-actions">
            <label className="button-inline button-ghost participant-import-button">
              CSV import
              <input type="file" accept=".csv,text/csv" onChange={importCsv} hidden />
            </label>
            {landscapeTemplates.length > 0 && (
              <button type="button" className="button-inline button-ghost" onClick={() => setExportModalOpen(true)}>
                Export
              </button>
            )}
            <button type="button" className="button-inline" onClick={openCreate}>
              Neuer Termin
            </button>
          </div>
        }
      />

      <details className="card import-help-card">
        <summary className="import-help-summary">
          <span>CSV-Format für Termine anzeigen</span>
          <span className="muted">Pflicht: Startdatum und Titel</span>
        </summary>
        <div className="import-help-body">
          <p className="muted">
            Unterstützte Spalten sind `Startdatum` oder `Datum`, optional `Enddatum`, `Tag`, `Titel`, `Beschreibung` und `Teilnehmerzahl`.
            Als Trennzeichen gehen Komma, Semikolon oder Tab. Datumsformate: `YYYY-MM-DD`, `DD.MM.YYYY`, `DD/MM/YYYY`.
          </p>
          <pre>{`Startdatum;Enddatum;Tag;Titel;Beschreibung;Teilnehmerzahl
2026-04-29;;Sitzung;Leiterrunde;Planung Sommerlager;8
12.07.2026;18.07.2026;Lager;Sommerlager;;42`}</pre>
        </div>
      </details>

      <div className="segment-control">
        <button
          type="button"
          className={`segment-button${tagFilter === "all" ? " segment-button-active" : ""}`}
          onClick={() => setTagFilter("all")}
        >
          Alle
        </button>
        {knownTags.map((tag) => (
          <button
            key={tag}
            type="button"
            className={`segment-button${tagFilter === tag ? " segment-button-active" : ""}`}
            onClick={() => setTagFilter(tag)}
          >
            {tag}
          </button>
        ))}
      </div>

      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={showParticipantCount}
          onChange={(event) => setShowParticipantCount(event.target.checked)}
        />
        Teilnehmerzahl in der Übersicht anzeigen
      </label>

      <article className="card">
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">Suche</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Termine durchsuchen" />
            <span className="field-help">
              Ohne Suche werden vergangene Termine ausgeblendet. Sobald du suchst, werden alle Termine beruecksichtigt.
            </span>
          </label>
          <div className="card">
            <div className="eyebrow">Überblick</div>
            <div className="status-row">
              <span className="pill">{filteredEvents.length} sichtbar</span>
              <span className="pill">{events.length} gesamt</span>
              <span className="pill">{knownTags.length} Tags</span>
            </div>
          </div>
        </div>
      </article>

      <DataTable
        columns={[
          { key: "event_date", label: "Datum", sortable: true, sortDirection: sortIndicator("event_date"), onSort: () => toggleSort("event_date") },
          { key: "title", label: "Titel", sortable: true, sortDirection: sortIndicator("title"), onSort: () => toggleSort("title") },
          { key: "tag", label: "Tag", sortable: true, sortDirection: sortIndicator("tag"), onSort: () => toggleSort("tag") },
          ...(showParticipantCount
            ? [
                {
                  key: "participant_count",
                  label: "Teilnehmer",
                  sortable: true,
                  sortDirection: sortIndicator("participant_count"),
                  onSort: () => toggleSort("participant_count"),
                } as const,
              ]
            : []),
          { key: "description", label: "Beschreibung", sortable: true, sortDirection: sortIndicator("description"), onSort: () => toggleSort("description") },
          "Aktionen",
        ]}
      >
        {filteredEvents.map((item) => (
          <tr key={item.id} className="table-row-clickable" onClick={() => openEdit(item)}>
            <td>{formatDateRange(item.event_date, item.event_end_date)}</td>
            <td>
              <strong>{item.title}</strong>
            </td>
            <td>{item.tag ? <span className="pill">{item.tag}</span> : <span className="muted">Kein Tag</span>}</td>
            {showParticipantCount ? <td>{item.participant_count ?? 0}</td> : null}
            <td>{item.description ?? <span className="muted">Keine Beschreibung</span>}</td>
            <td>
              <div className="table-actions table-actions-start">
                <button
                  type="button"
                  className="button-inline button-danger"
                  onClick={(clickEvent) => {
                    clickEvent.stopPropagation();
                    void deleteEvent(item.id);
                  }}
                >
                  Delete
                </button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>

      {hasMore && (
        <div className="load-more-row">
          <button type="button" className="button-inline button-ghost" onClick={() => void loadMore()} disabled={isLoadingMore}>
            {isLoadingMore ? "Lädt…" : `Mehr laden (${events.length} geladen)`}
          </button>
        </div>
      )}

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={form.id ? "Termin bearbeiten" : "Termin erstellen"}
        description="Der Tag hilft spaeter beim Verknuepfen mit passenden Protokollpunkten."
      >
        <form className="grid" onSubmit={saveEvent}>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Startdatum</span>
              <DateInput value={form.event_date} onChange={(value) => setForm((current) => ({ ...current, event_date: value }))} required />
            </label>
            <label className="field-stack">
              <span className="field-label">Enddatum</span>
              <DateInput value={form.event_end_date} onChange={(value) => setForm((current) => ({ ...current, event_end_date: value }))} />
              <span className="field-help">Leer lassen fuer einen einzelnen Tag.</span>
            </label>
          </div>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Tag</span>
              <input
                value={form.tag}
                onChange={(event) => setForm((current) => ({ ...current, tag: event.target.value }))}
                placeholder="z. B. Sitzung, Lager, Elternabend"
                list="event-tag-suggestions"
              />
              <datalist id="event-tag-suggestions">
                {knownTags.map((tag) => (
                  <option key={tag} value={tag} />
                ))}
              </datalist>
            </label>
            <label className="field-stack">
              <span className="field-label">Titel</span>
              <input value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} required />
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">Anzahl Teilnehmer</span>
            <input
              type="number"
              min="0"
              value={form.participant_count}
              onChange={(event) => setForm((current) => ({ ...current, participant_count: event.target.value }))}
            />
          </label>
          <label className="field-stack">
            <span className="field-label">Beschreibung</span>
            <textarea rows={5} value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} />
          </label>
          <label className="field-stack">
            <span className="field-label">Standort</span>
            <input value={form.location} onChange={(e) => setForm((current) => ({ ...current, location: e.target.value }))} placeholder="z. B. Gemeinschaftshaus, Sportplatz" />
          </label>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Spezial Text 1</span>
              <input value={form.spezial_text1} onChange={(e) => setForm((current) => ({ ...current, spezial_text1: e.target.value }))} />
            </label>
            <label className="field-stack">
              <span className="field-label">Spezial Text 2</span>
              <input value={form.spezial_text2} onChange={(e) => setForm((current) => ({ ...current, spezial_text2: e.target.value }))} />
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">Spezial Text 3</span>
            <input value={form.spezial_text3} onChange={(e) => setForm((current) => ({ ...current, spezial_text3: e.target.value }))} />
          </label>
          {availableParticipants.length > 0 && (
            <div className="field-stack">
              <span className="field-label">Personen</span>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {PARTICIPANT_ROLE_FIELDS.map(({ field, label }) => (
                  <div key={field} className="field-stack" style={{ gap: 4 }}>
                    <span className="field-label" style={{ fontSize: "0.78rem" }}>{label}</span>
                    <button
                      type="button"
                      className="button-ghost structured-list-picker"
                      onClick={() => openParticipantPicker(field)}
                      style={{ textAlign: "left", minHeight: 36, padding: "6px 10px", fontSize: "0.85rem" }}
                    >
                      {participantLabel(form[field] as number[])}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="field-stack">
            <span className="field-label">Zyklen</span>
            {cyclesLoading ? (
              <span className="muted" style={{ fontSize: "0.85rem" }}>Zyklen werden geladen…</span>
            ) : availableCycles.length === 0 ? (
              <span className="muted" style={{ fontSize: "0.85rem" }}>Keine Zyklen verfügbar (Zyklen unter Struktur → Zyklen anlegen)</span>
            ) : (
              <div className="cycle-chip-list">
                {availableCycles.map((cycle) => {
                  const active = form.cycle_assignments.some(
                    (a) => a.cycle_config_id === cycle.cycle_config_id && a.cycle_year === cycle.cycle_year
                  );
                  return (
                    <button
                      key={`${cycle.cycle_config_id}-${cycle.cycle_year}`}
                      type="button"
                      className={`cycle-chip${active ? " cycle-chip-active" : ""}`}
                      onClick={() => toggleCycle(cycle.cycle_config_id, cycle.cycle_year)}
                    >
                      {cycle.name}
                    </button>
                  );
                })}
              </div>
            )}
            <span className="field-help">Zyklen, denen dieser Termin zugeordnet werden soll. Optional.</span>
          </div>
          <button type="submit">{form.id ? "Termin speichern" : "Termin erstellen"}</button>
        </form>
      </Modal>

      <Modal
        open={Boolean(pickerField)}
        onClose={() => setPickerField(null)}
        title={PARTICIPANT_ROLE_FIELDS.find((r) => r.field === pickerField)?.label ?? "Teilnehmer wählen"}
        description="Mehrfachauswahl"
      >
        <div className="grid">
          <label className="field-stack">
            <span className="field-label">Suche</span>
            <input
              value={pickerSearch}
              onChange={(e) => setPickerSearch(e.target.value)}
              placeholder="Teilnehmer filtern"
            />
          </label>
          <div className="participant-check-grid">
            {availableParticipants
              .filter((p) => !pickerSearch.trim() || p.display_name.toLowerCase().includes(pickerSearch.toLowerCase()))
              .map((p) => {
                const checked = pickerSelected.includes(p.id);
                return (
                  <label key={p.id} className={`participant-check-card${checked ? " participant-check-card-active" : ""}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) =>
                        setPickerSelected((current) =>
                          e.target.checked ? [...current, p.id] : current.filter((id) => id !== p.id)
                        )
                      }
                    />
                    <span>{p.display_name}</span>
                  </label>
                );
              })}
          </div>
          <div className="table-toolbar-actions">
            <button type="button" className="button-inline" onClick={applyParticipantPicker}>
              Auswahl übernehmen
            </button>
          </div>
        </div>
      </Modal>

      <Modal open={exportModalOpen} title="Termine exportieren" onClose={() => setExportModalOpen(false)}>
        <div style={{ display: "grid", gap: "24px" }}>

          {knownExportTags.length > 0 && (
            <div className="field-stack">
              <span className="field-label">Tags</span>
              <div style={{ position: "relative" }}>
                <input
                  style={{ width: "100%", minHeight: 0, padding: "7px 12px", borderRadius: "10px", fontSize: "0.875rem", border: "1px solid var(--border)", background: "var(--surface, var(--panel-solid))", color: "var(--text)", outline: "none" }}
                  placeholder="Tag suchen…"
                  value={exportTagSearch}
                  onChange={(e) => setExportTagSearch(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Tab" && tagSuggestions.length > 0) {
                      e.preventDefault();
                      toggleExportTag(tagSuggestions[0]);
                      setExportTagSearch("");
                    } else if (e.key === "Enter" && tagSuggestions.length > 0) {
                      toggleExportTag(tagSuggestions[0]);
                      setExportTagSearch("");
                    } else if (e.key === "Escape") {
                      setExportTagSearch("");
                    }
                  }}
                />
                {tagSuggestions.length > 0 && (
                  <div style={{
                    position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0, zIndex: 100,
                    background: "var(--panel-solid)", border: "1px solid var(--border)",
                    borderRadius: "10px", boxShadow: "0 8px 24px rgba(0,0,0,0.28)",
                    overflow: "hidden",
                  }}>
                    {tagSuggestions.map((tag, i) => (
                      <button
                        key={tag}
                        type="button"
                        onMouseDown={(e) => { e.preventDefault(); toggleExportTag(tag); setExportTagSearch(""); }}
                        style={{
                          display: "flex", alignItems: "center", justifyContent: "space-between",
                          width: "100%", minHeight: 0, padding: "9px 12px", textAlign: "left",
                          background: i === 0 ? "color-mix(in srgb, var(--accent) 12%, var(--panel-solid) 88%)" : "var(--panel-solid)",
                          color: "var(--text)", fontSize: "0.9rem", border: "none",
                          borderBottom: i < tagSuggestions.length - 1 ? "1px solid var(--border)" : "none",
                          cursor: "pointer", borderRadius: 0,
                        }}
                      >
                        <span>{tag}</span>
                        {i === 0 && <span style={{ fontSize: "0.72rem", color: "var(--muted)", background: "var(--surface, var(--accent-soft))", padding: "2px 6px", borderRadius: "4px", border: "1px solid var(--border)" }}>Tab</span>}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="tag-filter-bar">
                {exportTagFilters.map((tag) => (
                  <button key={tag} type="button" className="tag-filter-chip tag-filter-chip-active"
                    onClick={() => toggleExportTag(tag)}
                    style={{ width: "auto", minHeight: 0, padding: "4px 12px", display: "inline-flex", fontSize: "0.85rem" }}
                  >{tag} ×</button>
                ))}
                {knownExportTags.filter((t) => !exportTagFilters.includes(t)).map((tag) => (
                  <button key={tag} type="button" className="tag-filter-chip"
                    onClick={() => toggleExportTag(tag)}
                    style={{ width: "auto", minHeight: 0, padding: "4px 12px", display: "inline-flex", fontSize: "0.85rem" }}
                  >{tag}</button>
                ))}
              </div>
            </div>
          )}

          <div className="field-stack">
            <span className="field-label">Zeitraum</span>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
              {(["all", "next-session", "until-event"] as const).map((mode) => {
                const label = mode === "all" ? "Alle Termine" : mode === "next-session" ? "Nächste Sitzung" : "Bis Termin";
                return (
                  <button key={mode} type="button"
                    className={`button-pill${exportDateMode === mode ? " button-pill-active" : ""}`}
                    onClick={() => { setExportDateMode(mode); setExportUrl(null); }}
                    style={{ width: "auto", minHeight: 0 }}
                  >{label}</button>
                );
              })}
            </div>
            {exportDateMode === "next-session" && (
              <span className="muted" style={{ fontSize: "0.82rem", paddingLeft: "2px" }}>
                {nextSessionEvent
                  ? `Bis ${nextSessionEvent.title} · ${formatDate(nextSessionEvent.event_date)}`
                  : "Keine Sitzung gefunden"}
              </span>
            )}
            {exportDateMode === "until-event" && (
              <select
                value={exportUntilEventId}
                onChange={(e) => { setExportUntilEventId(Number(e.target.value)); setExportUrl(null); }}
                style={{ width: "100%", minHeight: 0, padding: "7px 36px 7px 12px", borderRadius: "10px", fontSize: "0.875rem", border: "1px solid var(--border)", backgroundColor: "var(--panel-solid)", color: "var(--text)", appearance: "none", WebkitAppearance: "none", backgroundImage: "linear-gradient(45deg, transparent 50%, var(--muted) 50%), linear-gradient(135deg, var(--muted) 50%, transparent 50%)", backgroundPosition: "calc(100% - 18px) calc(50% - 2px), calc(100% - 12px) calc(50% - 2px)", backgroundSize: "6px 6px, 6px 6px", backgroundRepeat: "no-repeat" }}
              >
                <option value="">— Termin wählen —</option>
                {sortedEvents.map((ev) => (
                  <option key={ev.id} value={ev.id}>
                    {formatDate(ev.event_date)}{ev.tag ? ` · ${ev.tag}` : ""} — {ev.title}
                  </option>
                ))}
              </select>
            )}
          </div>

          <div style={{ display: "flex", gap: "10px", alignItems: "center", justifyContent: "space-between", borderTop: "1px solid var(--border)", paddingTop: "20px" }}>
            <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
            <button
              type="button"
              className={`pdf-icon-link pdf-icon-link-success${exportBusy || (!exportUrl && (!exportTemplateId || (exportDateMode === "until-event" && !exportUntilEventId) || (exportDateMode === "next-session" && !nextSessionEvent))) ? " pdf-icon-disabled" : ""}`}
              disabled={exportBusy || (!exportUrl && (!exportTemplateId || (exportDateMode === "until-event" && !exportUntilEventId) || (exportDateMode === "next-session" && !nextSessionEvent)))}
              onClick={() => void handlePdfClick()}
              title={exportUrl ? "PDF erneut herunterladen" : "PDF generieren"}
              style={{ width: "auto", minWidth: "56px", minHeight: 0, padding: "0 14px", display: "inline-flex", justifyContent: "center" }}
            >
              {exportBusy ? "..." : "PDF"}
            </button>
            <button
              type="button"
              className="pdf-icon-link pdf-icon-disabled"
              disabled
              title="Markdown-Export – kommt bald"
              style={{
                width: "auto", minWidth: "56px", minHeight: 0, padding: "0 14px", display: "inline-flex", justifyContent: "center",
                borderColor: "color-mix(in srgb, #a78bfa 28%, transparent 72%)",
                background: "color-mix(in srgb, #a78bfa 10%, transparent 90%)",
                color: "#a78bfa",
              }}
            >
              MD
            </button>
            </div>
            {landscapeTemplates.length > 0 && (
              <div ref={templateDropdownRef} style={{ position: "relative" }}>
                <button
                  type="button"
                  onClick={() => setTemplateDropdownOpen((v) => !v)}
                  style={{
                    width: "auto", minHeight: 0, height: "42px", padding: "0 32px 0 12px",
                    borderRadius: "14px", fontSize: "0.8rem",
                    border: "1px solid var(--border)", backgroundColor: "transparent",
                    color: "var(--text)", display: "flex", alignItems: "center", whiteSpace: "nowrap",
                    backgroundImage: "linear-gradient(45deg, transparent 50%, var(--muted) 50%), linear-gradient(135deg, var(--muted) 50%, transparent 50%)",
                    backgroundPosition: "calc(100% - 14px) calc(50% - 2px), calc(100% - 8px) calc(50% - 2px)",
                    backgroundSize: "6px 6px, 6px 6px", backgroundRepeat: "no-repeat",
                  }}
                >
                  {landscapeTemplates.find((t) => t.id === exportTemplateId)?.name ?? "Vorlage"}
                </button>
                {templateDropdownOpen && (
                  <div style={{
                    position: "absolute", bottom: "calc(100% + 4px)", right: 0, zIndex: 50,
                    backgroundColor: "var(--panel-solid)", border: "1px solid var(--border)",
                    borderRadius: "12px", boxShadow: "0 4px 20px rgba(0,0,0,0.22)",
                    overflow: "hidden", minWidth: "100%",
                  }}>
                    {landscapeTemplates.map((t, i) => (
                      <button
                        key={t.id}
                        type="button"
                        onMouseDown={() => { setExportTemplateId(t.id); setExportUrl(null); setTemplateDropdownOpen(false); }}
                        style={{
                          width: "100%", minHeight: 0, padding: "9px 14px",
                          textAlign: "left", fontSize: "0.88rem",
                          backgroundColor: "var(--panel-solid)",
                          color: "var(--text)",
                          fontWeight: t.id === exportTemplateId ? 700 : 400,
                          border: "none", borderRadius: 0,
                          borderBottom: i < landscapeTemplates.length - 1 ? "1px solid var(--border)" : "none",
                          cursor: "pointer", whiteSpace: "nowrap",
                        }}
                      >
                        {t.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

        </div>
      </Modal>
    </div>
  );
}
