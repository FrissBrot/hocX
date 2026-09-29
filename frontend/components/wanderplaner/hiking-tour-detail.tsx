"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
import { PillMenu } from "@/components/ui/pill-menu";
import { HikingTourElevationChart } from "@/components/wanderplaner/hiking-tour-elevation-chart";
import { HikingTourMap } from "@/components/wanderplaner/hiking-tour-map";
import { HikingTourMarchTable } from "@/components/wanderplaner/hiking-tour-march-table";
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import {
  ElevationProfile,
  ElevationProfilePoint,
  HikingTour,
  HikingTourRoutingProfile,
  HikingTourWaypoint,
  HikingTourWaypointKind,
  HikingTourWaypointVerificationStatus,
  MarchTimeTable,
} from "@/types/api";

// Auftrag Abschnitt 11: Verifizierungsstatus automatisch erkannter sicherheitsrelevanter
// Punkte (Entscheidungspunkte, Notausstiege) - nie als geprüfte Tatsache dargestellt.
const VERIFICATION_LABEL: Record<HikingTourWaypointVerificationStatus, string> = {
  AUTO_DETECTED: "Automatisch erkannt",
  NEEDS_VERIFICATION: "Vor Ort prüfen",
  VERIFIED: "Vom Leiter bestätigt",
  REJECTED: "Verworfen",
};

const VERIFICATION_VARIANT: Record<HikingTourWaypointVerificationStatus, BadgeVariant> = {
  AUTO_DETECTED: "info",
  NEEDS_VERIFICATION: "warning",
  VERIFIED: "success",
  REJECTED: "danger",
};

const VERIFICATION_OPTIONS = (Object.keys(VERIFICATION_LABEL) as HikingTourWaypointVerificationStatus[]).map((value) => ({
  value,
  label: VERIFICATION_LABEL[value],
  variant: VERIFICATION_VARIANT[value],
}));

// Auftrag Abschnitt 17 - dieselbe feste Item-Liste wie RECONNAISSANCE_CHECKLIST_ITEMS im
// Backend (app/schemas/hiking_tour.py), hier nur mit deutschen Labels.
const RECONNAISSANCE_CHECKLIST_LABELS: Record<string, string> = {
  trail_condition: "Wegzustand geprüft",
  problem_spots: "Problematische Stellen geprüft",
  exits: "Ausstiege geprüft",
  access_roads: "Zufahrten geprüft",
  water_points: "Wasserstellen geprüft",
  alternative_route: "Alternativroute geprüft",
  decision_points: "Wichtige Entscheidungspunkte geprüft",
};

function formatMinutesShort(minutes: number): string {
  const rounded = Math.round(minutes);
  const hours = Math.floor(rounded / 60);
  const rest = rounded % 60;
  return hours > 0 ? `${hours}h${rest.toString().padStart(2, "0")}` : `${rest}min`;
}

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

const ROUTING_PROFILE_LABEL: Record<HikingTourRoutingProfile, string> = {
  wanderwege_bevorzugen: "Wanderwege bevorzugen",
  schnellste_route: "Schnellste Route",
  einfache_route: "Einfache Route",
};

type EditFormState = { title: string; description: string; tour_date: string };

function formatDistance(meters: number | null): string {
  if (meters === null) return "–";
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`;
}

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
  const [placingVia, setPlacingVia] = useState(false);
  const [profile, setProfile] = useState<HikingTourRoutingProfile>(tour.routing_profile ?? "wanderwege_bevorzugen");
  const [saving, setSaving] = useState(false);
  const [computingRoute, setComputingRoute] = useState(false);
  const [elevationProfile, setElevationProfile] = useState<ElevationProfile | null>(null);
  const [fetchingElevation, setFetchingElevation] = useState(false);
  const [marchTable, setMarchTable] = useState<MarchTimeTable | null>(null);
  const [hoveredPoint, setHoveredPoint] = useState<ElevationProfilePoint | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [showReconnaissance, setShowReconnaissance] = useState(false);
  const [checklistDraft, setChecklistDraft] = useState<Record<string, boolean>>(tour.reconnaissance_checklist);
  const [remarksDraft, setRemarksDraft] = useState(tour.reconnaissance_remarks ?? "");
  const [savingReconnaissance, setSavingReconnaissance] = useState(false);
  const [approving, setApproving] = useState(false);

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
      setTour((prev) => ({ ...updated, route_legs: prev.route_legs }));
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

  async function handleMapClick(lat: number, lon: number) {
    if (!placingVia) return;
    setPlacingVia(false);
    try {
      const created = await browserApiFetch<HikingTourWaypoint>(`/api/hiking-tours/${tour.id}/waypoints`, {
        method: "POST",
        body: JSON.stringify({ lat, lon }),
      });
      setTour((prev) => ({ ...prev, waypoints: [...prev.waypoints, created].sort((a, b) => a.sequence - b.sequence) }));
      showToast("Via-Punkt hinzugefügt", "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Fehler beim Hinzufügen", "error");
    }
  }

  async function handleMarkerDragEnd(waypointId: string, lat: number, lon: number) {
    try {
      const updated = await browserApiFetch<HikingTourWaypoint>(`/api/hiking-tours/${tour.id}/waypoints/${waypointId}`, {
        method: "PATCH",
        body: JSON.stringify({ lat, lon }),
      });
      setTour((prev) => ({ ...prev, waypoints: prev.waypoints.map((wp) => (wp.id === updated.id ? updated : wp)) }));
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Punkt konnte nicht verschoben werden", "error");
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

  async function handleUpdateBreakMinutes(waypoint: HikingTourWaypoint, minutes: number) {
    try {
      const updated = await browserApiFetch<HikingTourWaypoint>(`/api/hiking-tours/${tour.id}/waypoints/${waypoint.id}`, {
        method: "PATCH",
        body: JSON.stringify({ break_minutes: minutes }),
      });
      setTour((prev) => ({ ...prev, waypoints: prev.waypoints.map((wp) => (wp.id === updated.id ? updated : wp)) }));
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Pause konnte nicht gespeichert werden", "error");
    }
  }

  async function handleComputeRoute() {
    setComputingRoute(true);
    try {
      const updated = await browserApiFetch<HikingTour>(`/api/hiking-tours/${tour.id}/route`, {
        method: "POST",
        body: JSON.stringify({ routing_profile: profile }),
      });
      setTour(updated);
      showToast("Route berechnet", "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Route konnte nicht berechnet werden", "error");
    } finally {
      setComputingRoute(false);
    }
  }

  useEffect(() => {
    if (tour.route_legs.length === 0) {
      setMarchTable(null);
      return;
    }
    let cancelled = false;
    browserApiFetch<MarchTimeTable>(`/api/hiking-tours/${tour.id}/march-table`)
      .then((table) => {
        if (!cancelled) setMarchTable(table);
      })
      .catch(() => {
        if (!cancelled) setMarchTable(null);
      });
    return () => {
      cancelled = true;
    };
  }, [tour.id, tour.route_computed_at, tour.route_legs.length]);

  useEffect(() => {
    if (!tour.elevation_profile_fetched_at) {
      setElevationProfile(null);
      return;
    }
    let cancelled = false;
    browserApiFetch<ElevationProfile>(`/api/hiking-tours/${tour.id}/elevation-profile`)
      .then((profile) => {
        if (!cancelled) setElevationProfile(profile);
      })
      .catch(() => {
        if (!cancelled) setElevationProfile(null);
      });
    return () => {
      cancelled = true;
    };
  }, [tour.id, tour.elevation_profile_fetched_at]);

  async function handleFetchElevationProfile() {
    setFetchingElevation(true);
    try {
      const updated = await browserApiFetch<HikingTour>(`/api/hiking-tours/${tour.id}/elevation-profile`, { method: "POST" });
      setTour((prev) => ({ ...updated, route_legs: prev.route_legs }));
      showToast("Höhenprofil abgerufen", "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Höhenprofil konnte nicht abgerufen werden", "error");
    } finally {
      setFetchingElevation(false);
    }
  }

  async function handleAnalyze() {
    setAnalyzing(true);
    try {
      const updated = await browserApiFetch<HikingTour>(`/api/hiking-tours/${tour.id}/analyze`, { method: "POST" });
      setTour(updated);
      showToast("Tour automatisch analysiert", "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Automatische Analyse fehlgeschlagen", "error");
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleVerificationChange(waypoint: HikingTourWaypoint, status: HikingTourWaypointVerificationStatus) {
    try {
      const updated = await browserApiFetch<HikingTourWaypoint>(`/api/hiking-tours/${tour.id}/waypoints/${waypoint.id}/verification`, {
        method: "PATCH",
        body: JSON.stringify({ verification_status: status }),
      });
      setTour((prev) => ({ ...prev, waypoints: prev.waypoints.map((wp) => (wp.id === updated.id ? updated : wp)) }));
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Status konnte nicht geändert werden", "error");
    }
  }

  async function handleSaveReconnaissance(event: FormEvent) {
    event.preventDefault();
    setSavingReconnaissance(true);
    try {
      const updated = await browserApiFetch<HikingTour>(`/api/hiking-tours/${tour.id}/reconnaissance`, {
        method: "PATCH",
        body: JSON.stringify({ checklist: checklistDraft, remarks: remarksDraft }),
      });
      setTour((prev) => ({ ...updated, route_legs: prev.route_legs }));
      setShowReconnaissance(false);
      showToast("Rekognoszierung gespeichert", "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Rekognoszierung konnte nicht gespeichert werden", "error");
    } finally {
      setSavingReconnaissance(false);
    }
  }

  async function handleApprove() {
    if (!(await confirm({ message: `Wanderung «${tour.title}» freigeben?`, confirmLabel: "Freigeben" }))) return;
    setApproving(true);
    try {
      const updated = await browserApiFetch<HikingTour>(`/api/hiking-tours/${tour.id}/approve`, { method: "POST" });
      setTour((prev) => ({ ...updated, route_legs: prev.route_legs }));
      showToast("Wanderung freigegeben", "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Freigabe fehlgeschlagen", "error");
    } finally {
      setApproving(false);
    }
  }

  const mapWaypoints = useMemo(
    () => tour.waypoints.map((wp) => ({ id: wp.id, kind: wp.kind, lat: wp.lat, lon: wp.lon, label: wp.label })),
    [tour.waypoints]
  );
  const routeCoordinates = useMemo<[number, number][]>(
    () => tour.route_legs.flatMap((leg) => leg.coordinates),
    [tour.route_legs]
  );

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
            <button type="button" className="button-secondary" onClick={() => setShowReconnaissance(true)}>
              Rekognoszierung
            </button>
            {tour.status === "reconnoitered" && (
              <button type="button" className="button-primary" onClick={() => void handleApprove()} disabled={approving}>
                {approving ? "Wird freigegeben…" : "Freigeben"}
              </button>
            )}
            <button type="button" className="button-danger" onClick={() => void handleDeleteTour()}>
              Löschen
            </button>
          </div>
        )}
      </div>

      <div className="section-card">
        <DataToolbar
          title="Karte & Route"
          description="Wegpunkte lassen sich per Ziehen verschieben. Neue Via-Punkte per Klick setzen."
          actions={
            canWrite ? (
              <div className="page-header-actions">
                <select value={profile} onChange={(event) => setProfile(event.target.value as HikingTourRoutingProfile)}>
                  {Object.entries(ROUTING_PROFILE_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
                <button type="button" className="button-secondary" onClick={() => void handleComputeRoute()} disabled={computingRoute}>
                  {computingRoute ? "Wird berechnet…" : "Route berechnen"}
                </button>
                <button
                  type="button"
                  className={placingVia ? "button-toggle button-toggle-active" : "button-toggle"}
                  onClick={() => setPlacingVia((value) => !value)}
                >
                  Via-Punkt hinzufügen
                </button>
              </div>
            ) : undefined
          }
        />
        {placingVia && <p className="field-help">Auf die Karte klicken, um den Via-Punkt zu platzieren.</p>}
        <HikingTourMap
          waypoints={mapWaypoints}
          routeCoordinates={routeCoordinates}
          onMapClick={canWrite ? handleMapClick : undefined}
          onMarkerDragEnd={canWrite ? handleMarkerDragEnd : undefined}
          highlightPoint={hoveredPoint ? { lat: hoveredPoint.lat, lon: hoveredPoint.lon } : null}
        />
        {tour.route_distance_m !== null && tour.route_distance_m !== undefined && (
          <div className="wanderplaner-route-summary">
            <span>
              Distanz: <strong>{formatDistance(tour.route_distance_m)}</strong>
            </span>
            <span>
              Aufstieg: <strong>{Math.round(tour.route_ascent_m ?? 0)} m</strong>
            </span>
            <span>
              Abstieg: <strong>{Math.round(tour.route_descent_m ?? 0)} m</strong>
            </span>
          </div>
        )}
      </div>

      {tour.route_legs.length > 0 && (
        <div className="section-card">
          <DataToolbar
            title="Höhenprofil"
            description="Aus swisstopo-Höhendaten (profile.json). Beim Überfahren markiert der Punkt die Stelle auf der Karte."
            actions={
              canWrite ? (
                <div className="page-header-actions">
                  <button type="button" className="button-secondary" onClick={() => void handleFetchElevationProfile()} disabled={fetchingElevation}>
                    {fetchingElevation ? "Wird abgerufen…" : "Höhenprofil abrufen"}
                  </button>
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={() => void handleAnalyze()}
                    disabled={analyzing || !tour.elevation_profile_fetched_at}
                    title={!tour.elevation_profile_fetched_at ? "Zuerst das Höhenprofil abrufen" : undefined}
                  >
                    {analyzing ? "Wird analysiert…" : "Automatisch analysieren"}
                  </button>
                </div>
              ) : undefined
            }
          />
          {elevationProfile ? (
            <HikingTourElevationChart points={elevationProfile.points} onHoverPoint={setHoveredPoint} />
          ) : (
            <p className="field-help">Noch kein Höhenprofil abgerufen.</p>
          )}
        </div>
      )}

      {marchTable && (
        <div className="section-card">
          <HikingTourMarchTable table={marchTable} />
        </div>
      )}

      <div>
        <DataToolbar title="Wegpunkte" description="Start, Ziel, Via-Punkte und automatisch erkannte Punkte in Reihenfolge." />
        <DataTable columns={["#", "Typ", "Bezeichnung", "Breite", "Länge", "Pause", "Status", ""]} emptyMessage="Keine Wegpunkte.">
          {tour.waypoints.map((waypoint) => (
            <tr key={waypoint.id}>
              <td>{waypoint.sequence}</td>
              <td>
                <Badge variant={waypoint.kind === "START" || waypoint.kind === "END" ? "info" : "neutral"}>{KIND_LABEL[waypoint.kind]}</Badge>
              </td>
              <td>
                {waypoint.label || <span className="muted">–</span>}
                {waypoint.description && <div className="field-help">{waypoint.description}</div>}
                {waypoint.decision_metrics_json && (
                  <div className="field-help">
                    Ab Start: {formatMinutesShort(waypoint.decision_metrics_json.time_from_start_minutes)} · Bis Ziel:{" "}
                    {formatMinutesShort(waypoint.decision_metrics_json.time_to_end_minutes)} · Zurück:{" "}
                    {formatMinutesShort(waypoint.decision_metrics_json.time_back_minutes)}
                    {waypoint.decision_metrics_json.nearest_exit_label && waypoint.decision_metrics_json.time_to_exit_minutes !== null && (
                      <> · Nächster Ausstieg: {formatMinutesShort(waypoint.decision_metrics_json.time_to_exit_minutes)}</>
                    )}
                  </div>
                )}
              </td>
              <td>{waypoint.lat.toFixed(4)}</td>
              <td>{waypoint.lon.toFixed(4)}</td>
              <td>
                {canWrite ? (
                  <input
                    key={`${waypoint.id}-${waypoint.break_minutes ?? 0}`}
                    type="number"
                    min={0}
                    defaultValue={waypoint.break_minutes ?? 0}
                    aria-label="Pause in Minuten"
                    className="wanderplaner-break-input"
                    onBlur={(event) => {
                      const minutes = Number(event.target.value) || 0;
                      if (minutes !== (waypoint.break_minutes ?? 0)) void handleUpdateBreakMinutes(waypoint, minutes);
                    }}
                  />
                ) : waypoint.break_minutes ? (
                  `${waypoint.break_minutes} min`
                ) : (
                  <span className="muted">–</span>
                )}
              </td>
              <td>
                {waypoint.verification_status ? (
                  canWrite ? (
                    <PillMenu
                      value={waypoint.verification_status}
                      options={VERIFICATION_OPTIONS}
                      onChange={(status) => void handleVerificationChange(waypoint, status)}
                    />
                  ) : (
                    <Badge variant={VERIFICATION_VARIANT[waypoint.verification_status]}>{VERIFICATION_LABEL[waypoint.verification_status]}</Badge>
                  )
                ) : (
                  <span className="muted">–</span>
                )}
              </td>
              <td className="wanderplaner-row-actions">
                {canWrite && (waypoint.kind === "USER_DEFINED" || waypoint.auto_generated) && (
                  <button type="button" className="button-secondary button-ghost" onClick={() => void handleDeleteWaypoint(waypoint)}>
                    Entfernen
                  </button>
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

      <Modal
        open={showReconnaissance}
        title="Rekognoszierung"
        onClose={() => setShowReconnaissance(false)}
      >
        <form onSubmit={(event) => void handleSaveReconnaissance(event)}>
          <div className="grid">
            {(tour.reconnoitered_at || tour.approved_at) && (
              <p className="muted">
                {tour.reconnoitered_at && (
                  <>
                    Rekognosziert {tour.reconnoitered_by_name ? `von ${tour.reconnoitered_by_name} ` : ""}
                    am {new Date(tour.reconnoitered_at).toLocaleDateString("de-CH")}.{" "}
                  </>
                )}
                {tour.approved_at && (
                  <>
                    Freigegeben {tour.approved_by_name ? `von ${tour.approved_by_name} ` : ""}
                    am {new Date(tour.approved_at).toLocaleDateString("de-CH")}.
                  </>
                )}
              </p>
            )}
            <div className="grid">
              {Object.entries(RECONNAISSANCE_CHECKLIST_LABELS).map(([key, label]) => (
                <label key={key} className="mini-menu-option">
                  <span>{label}</span>
                  <input
                    type="checkbox"
                    checked={checklistDraft[key] ?? false}
                    onChange={(event) => setChecklistDraft((prev) => ({ ...prev, [key]: event.target.checked }))}
                  />
                </label>
              ))}
            </div>
            <label className="field-stack">
              <span className="field-label">Weitere Bemerkungen</span>
              <textarea rows={3} value={remarksDraft} onChange={(event) => setRemarksDraft(event.target.value)} />
            </label>
          </div>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setShowReconnaissance(false)}>
              Abbrechen
            </button>
            <button type="submit" className="button-primary" disabled={savingReconnaissance}>
              {savingReconnaissance ? "Wird gespeichert…" : "Als rekognosziert markieren"}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
