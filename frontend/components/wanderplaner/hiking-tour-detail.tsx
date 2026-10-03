"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataToolbar } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
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
  HikingTourPrintResult,
  HikingTourRoutingProfile,
  HikingTourWaypoint,
  HikingTourWaypointKind,
  HikingTourWaypointVerificationStatus,
  MarchTimeTable,
} from "@/types/api";

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

// Auftrag Abschnitt 15 - dieselben Werte wie PAPER_SIZES_MM/DEFAULT_SCALES im Backend
// (app/core/print_layout.py); Architektur ist dort fuer weitere Massstaebe offen, hier nur
// die drei geforderten Presets.
const PRINT_PAPER_OPTIONS = ["A4", "A3", "A2", "A1"] as const;
const PRINT_SCALE_OPTIONS = [10_000, 25_000, 50_000] as const;

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
  NAVIGATION: "Fixpunkt",
  BREAK: "Pausenplatz",
  SUMMIT: "Gipfel",
  PASS: "Pass",
  HUT: "Hütte",
  WATER: "Wasser",
  DECISION: "Fixpunkt",
  EMERGENCY_EXIT: "Notausstieg",
  USER_DEFINED: "Fixpunkt",
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
  const [marchTableRevision, setMarchTableRevision] = useState(0);
  const [marchTable, setMarchTable] = useState<MarchTimeTable | null>(null);
  const [hoveredPoint, setHoveredPoint] = useState<ElevationProfilePoint | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [showReconnaissance, setShowReconnaissance] = useState(false);
  const [checklistDraft, setChecklistDraft] = useState<Record<string, boolean>>(tour.reconnaissance_checklist);
  const [remarksDraft, setRemarksDraft] = useState(tour.reconnaissance_remarks ?? "");
  const [savingReconnaissance, setSavingReconnaissance] = useState(false);
  const [approving, setApproving] = useState(false);
  const [showPrint, setShowPrint] = useState(false);
  const [printForm, setPrintForm] = useState({ paper: "A4", orientation: "landscape", scale: 25_000 });
  const [printing, setPrinting] = useState(false);
  const [printResult, setPrintResult] = useState<HikingTourPrintResult | null>(null);

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
      router.push("/hiking-planner");
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
      setMarchTableRevision((value) => value + 1);
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
        // Landesweites Wegenetz und mehrere Zwischenpunkte benötigen länger als 15s.
        signal: AbortSignal.timeout(180_000),
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
  }, [tour.id, tour.route_computed_at, tour.route_legs.length, marchTableRevision]);

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
    if (!(await confirm({
      message: "Für das Höhenprofil wird der Verlauf dieser Wanderroute an swisstopo (api3.geo.admin.ch) übertragen. Konto- und Teilnehmerdaten werden nicht mitgesendet. Möchtest du diesen Abruf erlauben?",
      confirmLabel: "Abruf erlauben",
    }))) return;
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
      const updated = await browserApiFetch<HikingTour>(`/api/hiking-tours/${tour.id}/analyze`, { method: "POST", signal: AbortSignal.timeout(180_000) });
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

  async function handlePrint(event: FormEvent) {
    event.preventDefault();
    setPrinting(true);
    setPrintResult(null);
    try {
      const result = await browserApiFetch<HikingTourPrintResult>(`/api/hiking-tours/${tour.id}/print`, {
        method: "POST",
        body: JSON.stringify({
          paper: printForm.paper,
          orientation: printForm.orientation,
          scale: printForm.scale,
        }),
        // browserApiFetch's Standard-Timeout (15s) reicht nicht: WMTS-Kachelabruf + pdflatex-
        // Kompilierung dauern je nach Blattanzahl/Massstab real 20-60+ Sekunden (siehe
        // hiking_tour_print_service.py - der Backend-seitige pdflatex-Timeout selbst ist schon
        // 120s). Ohne diese Ueberschreibung brach der Request client-seitig ab, waehrend der
        // Server noch am Rechnen war (gefunden per echtem E2E-Test gegen den echten
        // swisstopo-Dienst, nicht nur durch gemockte Unit-Tests).
        signal: AbortSignal.timeout(180_000),
      });
      setPrintResult(result);
      showToast("Druck-PDF erstellt", "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Druck-PDF konnte nicht erstellt werden", "error");
    } finally {
      setPrinting(false);
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
            {tour.route_legs.length > 0 && (
              <button type="button" className="button-secondary" onClick={() => { setPrintResult(null); setShowPrint(true); }}>
                Drucken
              </button>
            )}
            {tour.route_legs.length > 0 && (
              <a className="button-secondary" href={`/api/hiking-tours/${tour.id}/gpx`}>
                GPX exportieren
              </a>
            )}
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
            description="Beim Überfahren markiert das Höhenprofil die Stelle auf der Karte. Die automatische Analyse ergänzt markante Verzweigungen, Querungen und Hütten – ungefähr alle 15 Gehminuten."
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

      <div className="section-card">
        <HikingTourMarchTable
          table={marchTable}
          waypoints={tour.waypoints}
          canWrite={canWrite}
          onUpdateBreakMinutes={(waypoint, minutes) => void handleUpdateBreakMinutes(waypoint, minutes)}
          onVerificationChange={(waypoint, status) => void handleVerificationChange(waypoint, status)}
          onDeleteWaypoint={(waypoint) => void handleDeleteWaypoint(waypoint)}
        />
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

      <Modal open={showPrint} title="Drucken" onClose={() => setShowPrint(false)}>
        <form onSubmit={(event) => void handlePrint(event)}>
          <div className="grid two-col">
            <label className="field-stack">
              <span className="field-label">Papierformat</span>
              <select value={printForm.paper} onChange={(event) => setPrintForm((prev) => ({ ...prev, paper: event.target.value }))}>
                {PRINT_PAPER_OPTIONS.map((paper) => (
                  <option key={paper} value={paper}>
                    {paper}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-stack">
              <span className="field-label">Ausrichtung</span>
              <select
                value={printForm.orientation}
                onChange={(event) => setPrintForm((prev) => ({ ...prev, orientation: event.target.value }))}
              >
                <option value="portrait">Hochformat</option>
                <option value="landscape">Querformat</option>
              </select>
            </label>
            <label className="field-stack">
              <span className="field-label">Massstab</span>
              <select
                value={printForm.scale}
                onChange={(event) => setPrintForm((prev) => ({ ...prev, scale: Number(event.target.value) }))}
              >
                {PRINT_SCALE_OPTIONS.map((scale) => (
                  <option key={scale} value={scale}>
                    1:{scale.toLocaleString("de-CH")}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {printResult && (
            <p className="field-help">
              PDF mit {printResult.sheet_count} Kartenblatt{printResult.sheet_count === 1 ? "" : "blättern"} erstellt -{" "}
              <a href={printResult.content_url} target="_blank" rel="noreferrer">
                PDF herunterladen
              </a>
              .
            </p>
          )}
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setShowPrint(false)}>
              Schliessen
            </button>
            <button type="submit" className="button-primary" disabled={printing}>
              {printing ? "Wird erstellt…" : "PDF erstellen"}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
