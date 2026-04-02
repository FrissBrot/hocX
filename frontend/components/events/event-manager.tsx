"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateRange } from "@/lib/utils/format";
import { EventSummary } from "@/types/api";

type Props = {
  initialEvents: EventSummary[];
};

type EventFormState = {
  id?: number;
  event_date: string;
  event_end_date: string;
  tag: string;
  title: string;
  description: string;
  participant_count: string;
};

function emptyForm(): EventFormState {
  return {
    event_date: new Date().toISOString().slice(0, 10),
    event_end_date: "",
    tag: "",
    title: "",
    description: "",
    participant_count: "0",
  };
}

export function EventManager({ initialEvents }: Props) {
  const [events, setEvents] = useState(initialEvents);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("Bereit");
  const [statusTone, setStatusTone] = useState<"neutral" | "success" | "error">("neutral");
  const [tagFilter, setTagFilter] = useState("all");
  const [sortKey, setSortKey] = useState<"event_date" | "title" | "tag" | "description" | "participant_count">("event_date");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [showParticipantCount, setShowParticipantCount] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<EventFormState>(emptyForm);
  const [todayIso, setTodayIso] = useState("0000-01-01");

  useEffect(() => {
    setTodayIso(new Date().toISOString().slice(0, 10));
  }, []);

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

  function toggleSort(nextKey: "event_date" | "title" | "tag" | "description" | "participant_count") {
    setSortKey((currentKey) => {
      if (currentKey === nextKey) {
        setSortDirection((currentDirection) => (currentDirection === "asc" ? "desc" : "asc"));
        return currentKey;
      }
      setSortDirection("asc");
      return nextKey;
    });
  }

  function openCreate() {
    setForm(emptyForm());
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
    });
    setModalOpen(true);
  }

  async function saveEvent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus(form.id ? "Termin wird gespeichert..." : "Termin wird erstellt...");
    setStatusTone("neutral");
    try {
      const payload = {
        event_date: form.event_date,
        event_end_date: form.event_end_date || null,
        tag: form.tag || null,
        title: form.title,
        description: form.description || null,
        participant_count: Math.max(0, Number(form.participant_count || "0")),
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
      setStatus(form.id ? "Termin gespeichert" : "Termin erstellt");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Termin konnte nicht gespeichert werden");
      setStatusTone("error");
    }
  }

  async function deleteEvent(eventId: number) {
    setStatus("Termin wird gelöscht...");
    setStatusTone("neutral");
    try {
      await browserApiFetch(`/api/events/${eventId}`, { method: "DELETE" });
      setEvents((current) => current.filter((event) => event.id !== eventId));
      setStatus("Termin gelöscht");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Termin konnte nicht gelöscht werden");
      setStatusTone("error");
    }
  }

  async function importCsv(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setStatus(`Importiere ${file.name}...`);
    setStatusTone("neutral");
    try {
      const body = new FormData();
      body.append("file", file);
      const imported = await browserApiFetch<EventSummary[]>("/api/events/import-csv", {
        method: "POST",
        body,
      });
      setEvents((current) => [...imported, ...current]);
      setStatus(`${imported.length} Termine importiert`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "CSV-Import fehlgeschlagen");
      setStatusTone("error");
    } finally {
      event.target.value = "";
    }
  }

  return (
    <div className="grid">
      {status !== "Bereit" ? <StatusBanner tone={statusTone} message={status} /> : null}

      <DataToolbar
        title="Termine"
        actions={
          <div className="table-toolbar-actions">
            <label className="button-inline button-ghost participant-import-button">
              CSV import
              <input type="file" accept=".csv,text/csv" onChange={importCsv} hidden />
            </label>
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
          { key: "event_date", label: "Datum", sortable: true, sortDirection: sortKey === "event_date" ? sortDirection : null, onSort: () => toggleSort("event_date") },
          { key: "title", label: "Titel", sortable: true, sortDirection: sortKey === "title" ? sortDirection : null, onSort: () => toggleSort("title") },
          { key: "tag", label: "Tag", sortable: true, sortDirection: sortKey === "tag" ? sortDirection : null, onSort: () => toggleSort("tag") },
          ...(showParticipantCount
            ? [
                {
                  key: "participant_count",
                  label: "Teilnehmer",
                  sortable: true,
                  sortDirection: sortKey === "participant_count" ? sortDirection : null,
                  onSort: () => toggleSort("participant_count"),
                } as const,
              ]
            : []),
          { key: "description", label: "Beschreibung", sortable: true, sortDirection: sortKey === "description" ? sortDirection : null, onSort: () => toggleSort("description") },
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
              <input type="date" value={form.event_date} onChange={(event) => setForm((current) => ({ ...current, event_date: event.target.value }))} required />
            </label>
            <label className="field-stack">
              <span className="field-label">Enddatum</span>
              <input type="date" value={form.event_end_date} onChange={(event) => setForm((current) => ({ ...current, event_end_date: event.target.value }))} />
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
          <button type="submit">{form.id ? "Termin speichern" : "Termin erstellen"}</button>
        </form>
      </Modal>
    </div>
  );
}
