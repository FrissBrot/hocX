"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { HikingTour, HikingTourWaypoint, HikingTourWaypointKind } from "@/types/api";

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

const KIND_LABEL: Record<HikingTourWaypointKind, string> = {
  START: "Start",
  END: "Ziel",
  NAVIGATION: "Wegpunkt",
  BREAK: "Pause",
  SUMMIT: "Gipfel",
  PASS: "Pass",
  HUT: "Hütte",
  WATER: "Wasserstelle",
  DECISION: "Entscheidungspunkt",
  EMERGENCY_EXIT: "Notausstieg",
  USER_DEFINED: "Via-Punkt",
};

type EditFormState = {
  title: string;
  description: string;
  tour_date: string;
};

type ViaPointFormState = {
  label: string;
  description: string;
  lat: string;
  lon: string;
};

const EMPTY_VIA_FORM: ViaPointFormState = { label: "", description: "", lat: "", lon: "" };

export function HikingTourDetail({ initialTour, canWrite }: { initialTour: HikingTour; canWrite: boolean }) {
  const router = useRouter();
  const confirm = useConfirm();
  const showToast = useToast();
  const [tour, setTour] = useState(initialTour);
  const [showEdit, setShowEdit] = useState(false);
  const [editForm, setEditForm] = useState<EditFormState>({
    title: tour.title,
    description: tour.description ?? "",
    tour_date: tour.tour_date ?? "",
  });
  const [showAddVia, setShowAddVia] = useState(false);
  const [viaForm, setViaForm] = useState<ViaPointFormState>(EMPTY_VIA_FORM);
  const [movingWaypointId, setMovingWaypointId] = useState<string | null>(null);
  const [moveForm, setMoveForm] = useState<ViaPointFormState>(EMPTY_VIA_FORM);
  const [saving, setSaving] = useState(false);

  async function handleEditSave(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      const updated = await browserApiFetch<HikingTour>(`/api/hiking-tours/${tour.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: editForm.title.trim(),
          description: editForm.description.trim() || null,
          tour_date: editForm.tour_date || null,
        }),
      });
      setTour(updated);
      setShowEdit(false);
      showToast("Wanderung gespeichert", "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Fehler beim Speichern", "error");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteTour() {
    if (!(await confirm({ message: `Wanderung «${tour.title}» wirklich löschen?`, tone: "danger", confirmLabel: "Löschen" }))) return;
    try {
      await browserApiFetch(`/api/hiking-tours/${tour.id}`, { method: "DELETE" });
      showToast("Wanderung gelöscht", "success");
      router.push("/wanderplaner");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Fehler beim Löschen", "error");
    }
  }

  async function handleAddVia(event: FormEvent) {
    event.preventDefault();
    const lat = Number(viaForm.lat);
    const lon = Number(viaForm.lon);
    if (Number.isNaN(lat) || Number.isNaN(lon)) {
      showToast("Ungültige Koordinaten", "error");
      return;
    }
    setSaving(true);
    try {
      const created = await browserApiFetch<HikingTourWaypoint>(`/api/hiking-tours/${tour.id}/waypoints`, {
        method: "POST",
        body: JSON.stringify({ lat, lon, label: viaForm.label.trim() || null, description: viaForm.description.trim() || null }),
      });
      setTour((prev) => ({
        ...prev,
        waypoints: [...prev.waypoints, created].sort((a, b) => a.sequence - b.sequence),
      }));
      setShowAddVia(false);
      setViaForm(EMPTY_VIA_FORM);
      showToast("Via-Punkt hinzugefügt", "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Fehler beim Hinzufügen", "error");
    } finally {
      setSaving(false);
    }
  }

  function openMove(waypoint: HikingTourWaypoint) {
    setMovingWaypointId(waypoint.id);
    setMoveForm({ label: waypoint.label ?? "", description: waypoint.description ?? "", lat: String(waypoint.lat), lon: String(waypoint.lon) });
  }

  async function handleMoveSave(event: FormEvent) {
    event.preventDefault();
    if (!movingWaypointId) return;
    const lat = Number(moveForm.lat);
    const lon = Number(moveForm.lon);
    if (Number.isNaN(lat) || Number.isNaN(lon)) {
      showToast("Ungültige Koordinaten", "error");
      return;
    }
    setSaving(true);
    try {
      const updated = await browserApiFetch<HikingTourWaypoint>(`/api/hiking-tours/${tour.id}/waypoints/${movingWaypointId}`, {
        method: "PATCH",
        body: JSON.stringify({ lat, lon, label: moveForm.label.trim() || null, description: moveForm.description.trim() || null }),
      });
      setTour((prev) => ({ ...prev, waypoints: prev.waypoints.map((wp) => (wp.id === updated.id ? updated : wp)) }));
      setMovingWaypointId(null);
      showToast("Punkt gespeichert", "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Fehler beim Speichern", "error");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteWaypoint(waypoint: HikingTourWaypoint) {
    if (!(await confirm({ message: `Punkt «${waypoint.label ?? KIND_LABEL[waypoint.kind]}» entfernen?`, tone: "danger", confirmLabel: "Entfernen" }))) return;
    try {
      await browserApiFetch(`/api/hiking-tours/${tour.id}/waypoints/${waypoint.id}`, { method: "DELETE" });
      setTour((prev) => ({ ...prev, waypoints: prev.waypoints.filter((wp) => wp.id !== waypoint.id) }));
      showToast("Punkt entfernt", "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Fehler beim Entfernen", "error");
    }
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{tour.title}</h1>
          <p className="muted">{tour.description || "Keine Beschreibung"}</p>
          <Badge variant={STATUS_VARIANT[tour.status] ?? "neutral"}>{STATUS_LABEL[tour.status] ?? tour.status}</Badge>
        </div>
        {canWrite && (
          <div className="page-header-actions">
            <button type="button" className="button-secondary" onClick={() => setShowEdit(true)}>
              Bearbeiten
            </button>
            <button type="button" className="button-danger" onClick={() => void handleDeleteTour()}>
              Löschen
            </button>
          </div>
        )}
      </div>

      <div>
        <DataToolbar
          title="Wegpunkte"
          description="Start, Ziel und Via-Punkte in Reihenfolge. Kartenbasierte Bearbeitung und automatische Wegpunkte folgen in einer späteren Ausbaustufe."
          actions={
            canWrite ? (
              <button type="button" className="button-secondary" onClick={() => setShowAddVia(true)}>
                Via-Punkt hinzufügen
              </button>
            ) : undefined
          }
        />
        <DataTable columns={["#", "Typ", "Bezeichnung", "Breite", "Länge", ""]} emptyMessage="Keine Wegpunkte.">
          {tour.waypoints.map((waypoint) => (
            <tr key={waypoint.id}>
              <td>{waypoint.sequence}</td>
              <td>
                <Badge variant={waypoint.kind === "START" || waypoint.kind === "END" ? "info" : "neutral"}>{KIND_LABEL[waypoint.kind]}</Badge>
              </td>
              <td>{waypoint.label || <span className="muted">–</span>}</td>
              <td>{waypoint.lat.toFixed(4)}</td>
              <td>{waypoint.lon.toFixed(4)}</td>
              <td className="wanderplaner-row-actions">
                {canWrite && (
                  <>
                    <button type="button" className="button-secondary button-ghost" onClick={() => openMove(waypoint)}>
                      Verschieben
                    </button>
                    {waypoint.kind === "USER_DEFINED" && (
                      <button type="button" className="button-secondary button-ghost" onClick={() => void handleDeleteWaypoint(waypoint)}>
                        Entfernen
                      </button>
                    )}
                  </>
                )}
              </td>
            </tr>
          ))}
        </DataTable>
      </div>

      <Modal open={showEdit} title="Wanderung bearbeiten" onClose={() => setShowEdit(false)}>
        <form onSubmit={(event) => void handleEditSave(event)}>
          <div className="grid">
            <label className="field-stack">
              <span className="field-label">Titel</span>
              <input required value={editForm.title} onChange={(event) => setEditForm({ ...editForm, title: event.target.value })} />
            </label>
            <label className="field-stack">
              <span className="field-label">Beschreibung</span>
              <textarea rows={3} value={editForm.description} onChange={(event) => setEditForm({ ...editForm, description: event.target.value })} />
            </label>
            <label className="field-stack">
              <span className="field-label">Datum</span>
              <DateInput value={editForm.tour_date} onChange={(value) => setEditForm({ ...editForm, tour_date: value })} />
            </label>
          </div>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setShowEdit(false)}>
              Abbrechen
            </button>
            <button type="submit" className="button-primary" disabled={saving}>
              {saving ? "Wird gespeichert…" : "Speichern"}
            </button>
          </div>
        </form>
      </Modal>

      <Modal open={showAddVia} title="Via-Punkt hinzufügen" onClose={() => setShowAddVia(false)}>
        <form onSubmit={(event) => void handleAddVia(event)}>
          <div className="grid">
            <label className="field-stack">
              <span className="field-label">Bezeichnung</span>
              <input value={viaForm.label} onChange={(event) => setViaForm({ ...viaForm, label: event.target.value })} />
            </label>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">Breite (Lat)</span>
                <input required type="number" step="0.0001" value={viaForm.lat} onChange={(event) => setViaForm({ ...viaForm, lat: event.target.value })} />
              </label>
              <label className="field-stack">
                <span className="field-label">Länge (Lon)</span>
                <input required type="number" step="0.0001" value={viaForm.lon} onChange={(event) => setViaForm({ ...viaForm, lon: event.target.value })} />
              </label>
            </div>
          </div>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setShowAddVia(false)}>
              Abbrechen
            </button>
            <button type="submit" className="button-primary" disabled={saving}>
              {saving ? "Wird hinzugefügt…" : "Hinzufügen"}
            </button>
          </div>
        </form>
      </Modal>

      <Modal open={movingWaypointId !== null} title="Punkt verschieben" onClose={() => setMovingWaypointId(null)}>
        <form onSubmit={(event) => void handleMoveSave(event)}>
          <div className="grid">
            <label className="field-stack">
              <span className="field-label">Bezeichnung</span>
              <input value={moveForm.label} onChange={(event) => setMoveForm({ ...moveForm, label: event.target.value })} />
            </label>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">Breite (Lat)</span>
                <input required type="number" step="0.0001" value={moveForm.lat} onChange={(event) => setMoveForm({ ...moveForm, lat: event.target.value })} />
              </label>
              <label className="field-stack">
                <span className="field-label">Länge (Lon)</span>
                <input required type="number" step="0.0001" value={moveForm.lon} onChange={(event) => setMoveForm({ ...moveForm, lon: event.target.value })} />
              </label>
            </div>
          </div>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setMovingWaypointId(null)}>
              Abbrechen
            </button>
            <button type="submit" className="button-primary" disabled={saving}>
              {saving ? "Wird gespeichert…" : "Speichern"}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
