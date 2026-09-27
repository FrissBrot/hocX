"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
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

type TourFormState = {
  title: string;
  description: string;
  tour_date: string;
  start_lat: string;
  start_lon: string;
  end_lat: string;
  end_lon: string;
};

const EMPTY_FORM: TourFormState = {
  title: "",
  description: "",
  tour_date: "",
  start_lat: "",
  start_lon: "",
  end_lat: "",
  end_lon: "",
};

export function HikingTourManager({ initialTours, canWrite }: { initialTours: HikingTourSummary[]; canWrite: boolean }) {
  const router = useRouter();
  const showToast = useToast();
  const [tours, setTours] = useState(initialTours);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<TourFormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    const startLat = Number(form.start_lat);
    const startLon = Number(form.start_lon);
    const endLat = Number(form.end_lat);
    const endLon = Number(form.end_lon);
    if ([startLat, startLon, endLat, endLon].some((value) => Number.isNaN(value))) {
      showToast("Start und Ziel brauchen gültige Koordinaten", "error");
      return;
    }
    setSaving(true);
    try {
      const created = await browserApiFetch<HikingTour>("/api/hiking-tours", {
        method: "POST",
        body: JSON.stringify({
          title: form.title.trim(),
          description: form.description.trim() || null,
          tour_date: form.tour_date || null,
          start: { lat: startLat, lon: startLon },
          end: { lat: endLat, lon: endLon },
          via_points: [],
        }),
      });
      setTours((prev) => [
        { id: created.id, title: created.title, tour_date: created.tour_date, status: created.status, created_at: created.created_at, updated_at: created.updated_at },
        ...prev,
      ]);
      setShowCreate(false);
      setForm(EMPTY_FORM);
      showToast("Wanderung erstellt", "success");
      router.push(`/wanderplaner/${created.id}`);
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Fehler beim Erstellen", "error");
    } finally {
      setSaving(false);
    }
  }

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

      <Modal open={showCreate} title="Neue Wanderung" onClose={() => setShowCreate(false)} size="wide">
        <form onSubmit={(event) => void handleCreate(event)}>
          <div className="grid">
            <label className="field-stack">
              <span className="field-label">Titel</span>
              <input required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} />
            </label>
            <label className="field-stack">
              <span className="field-label">Beschreibung</span>
              <textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} rows={3} />
            </label>
            <label className="field-stack">
              <span className="field-label">Datum</span>
              <DateInput value={form.tour_date} onChange={(value) => setForm({ ...form, tour_date: value })} />
              <span className="field-help">Optional.</span>
            </label>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">Start – Breite (Lat)</span>
                <input required type="number" step="0.0001" value={form.start_lat} onChange={(event) => setForm({ ...form, start_lat: event.target.value })} />
              </label>
              <label className="field-stack">
                <span className="field-label">Start – Länge (Lon)</span>
                <input required type="number" step="0.0001" value={form.start_lon} onChange={(event) => setForm({ ...form, start_lon: event.target.value })} />
              </label>
            </div>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">Ziel – Breite (Lat)</span>
                <input required type="number" step="0.0001" value={form.end_lat} onChange={(event) => setForm({ ...form, end_lat: event.target.value })} />
              </label>
              <label className="field-stack">
                <span className="field-label">Ziel – Länge (Lon)</span>
                <input required type="number" step="0.0001" value={form.end_lon} onChange={(event) => setForm({ ...form, end_lon: event.target.value })} />
              </label>
            </div>
            <span className="field-help">
              Koordinaten vorerst als Zahlenwerte (WGS84) – Setzen per Karte folgt in einer späteren Ausbaustufe.
            </span>
          </div>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setShowCreate(false)}>
              Abbrechen
            </button>
            <button type="submit" className="button-primary" disabled={saving}>
              {saving ? "Wird erstellt…" : "Wanderung erstellen"}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
