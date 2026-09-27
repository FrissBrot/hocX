"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
import { HikingTourMap } from "@/components/wanderplaner/hiking-tour-map";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { formatDate } from "@/lib/utils/format";
import { HikingTour, HikingTourSummary } from "@/types/api";

const STATUS_LABEL: Record<string, string> = {
  draft: "Entwurf",
  analyzed: "Automatisch analysiert",
  reconnoitered: "Rekognosziert",
  approved: "Freigegeben",
};

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  draft: "neutral",
  analyzed: "info",
  reconnoitered: "warning",
  approved: "success",
};

type LatLon = { lat: number; lon: number };

export function HikingTourManager({ initialTours, canWrite }: { initialTours: HikingTourSummary[]; canWrite: boolean }) {
  const router = useRouter();
  const showToast = useToast();
  const [tours, setTours] = useState(initialTours);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tourDate, setTourDate] = useState("");
  const [start, setStart] = useState<LatLon | null>(null);
  const [end, setEnd] = useState<LatLon | null>(null);
  const [pendingField, setPendingField] = useState<"start" | "end">("start");
  const [saving, setSaving] = useState(false);

  function resetCreateForm() {
    setTitle("");
    setDescription("");
    setTourDate("");
    setStart(null);
    setEnd(null);
    setPendingField("start");
  }

  function handleMapClick(lat: number, lon: number) {
    if (pendingField === "start") {
      setStart({ lat, lon });
      setPendingField("end");
    } else {
      setEnd({ lat, lon });
    }
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!start || !end) {
      showToast("Bitte Start und Ziel auf der Karte setzen", "error");
      return;
    }
    setSaving(true);
    try {
      const created = await browserApiFetch<HikingTour>("/api/hiking-tours", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          description: description.trim() || null,
          tour_date: tourDate || null,
          start,
          end,
          via_points: [],
        }),
      });
      setTours((prev) => [
        { id: created.id, title: created.title, tour_date: created.tour_date, status: created.status, created_at: created.created_at, updated_at: created.updated_at },
        ...prev,
      ]);
      setShowCreate(false);
      resetCreateForm();
      showToast("Wanderung erstellt", "success");
      router.push(`/wanderplaner/${created.id}`);
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Fehler beim Erstellen", "error");
    } finally {
      setSaving(false);
    }
  }

  const mapWaypoints = [
    ...(start ? [{ id: "start", kind: "START" as const, lat: start.lat, lon: start.lon }] : []),
    ...(end ? [{ id: "end", kind: "END" as const, lat: end.lat, lon: end.lon }] : []),
  ];

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">Wanderplaner</h1>
          <p className="muted">Wanderungen planen, Route berechnen und Marschzeittabelle erstellen.</p>
        </div>
        {canWrite && (
          <button type="button" className="button-primary" onClick={() => setShowCreate(true)}>
            Neue Wanderung
          </button>
        )}
      </div>

      <div>
        <DataToolbar title="Wanderungen" />
        <DataTable columns={["Titel", "Datum", "Status"]} emptyMessage="Noch keine Wanderungen geplant.">
          {tours.map((tour) => (
            <tr key={tour.id} className="table-row-clickable" onClick={() => router.push(`/wanderplaner/${tour.id}`)}>
              <td>{tour.title}</td>
              <td>{tour.tour_date ? formatDate(tour.tour_date) : <span className="muted">–</span>}</td>
              <td>
                <Badge variant={STATUS_VARIANT[tour.status] ?? "neutral"}>{STATUS_LABEL[tour.status] ?? tour.status}</Badge>
              </td>
            </tr>
          ))}
        </DataTable>
      </div>

      <Modal
        open={showCreate}
        title="Neue Wanderung"
        onClose={() => {
          setShowCreate(false);
          resetCreateForm();
        }}
        size="wide"
      >
        <form onSubmit={(event) => void handleCreate(event)}>
          <div className="grid">
            <label className="field-stack">
              <span className="field-label">Titel</span>
              <input required value={title} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label className="field-stack">
              <span className="field-label">Beschreibung</span>
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={2} />
            </label>
            <label className="field-stack">
              <span className="field-label">Datum</span>
              <DateInput value={tourDate} onChange={setTourDate} />
              <span className="field-help">Optional.</span>
            </label>

            <div className="field-stack">
              <span className="field-label">Start und Ziel</span>
              <div className="wanderplaner-map-hint">
                <div className="wanderplaner-toggle-group">
                  <button
                    type="button"
                    className={pendingField === "start" ? "button-toggle button-toggle-active" : "button-toggle"}
                    onClick={() => setPendingField("start")}
                  >
                    Start setzen{start ? " ✓" : ""}
                  </button>
                  <button
                    type="button"
                    className={pendingField === "end" ? "button-toggle button-toggle-active" : "button-toggle"}
                    onClick={() => setPendingField("end")}
                  >
                    Ziel setzen{end ? " ✓" : ""}
                  </button>
                </div>
                <span className="field-help">
                  Auf die Karte klicken, um {pendingField === "start" ? "den Start" : "das Ziel"} zu setzen.
                </span>
              </div>
              <HikingTourMap waypoints={mapWaypoints} onMapClick={handleMapClick} className="wanderplaner-map-compact" />
            </div>
          </div>
          <div className="modal-actions">
            <button
              type="button"
              className="button-ghost"
              onClick={() => {
                setShowCreate(false);
                resetCreateForm();
              }}
            >
              Abbrechen
            </button>
            <button type="submit" className="button-primary" disabled={saving || !start || !end}>
              {saving ? "Wird erstellt…" : "Wanderung erstellen"}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
