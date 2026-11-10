"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useMemo, useState } from "react";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataToolbar } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
import { Select } from "@/components/ui/select";
import { HikingTourElevationChart } from "@/components/wanderplaner/hiking-tour-elevation-chart";
import { HikingTourLoadingLandscape } from "@/components/wanderplaner/hiking-tour-loading-landscape";
import { HikingTourMap } from "@/components/wanderplaner/hiking-tour-map";
import { HikingTourMarchTable } from "@/components/wanderplaner/hiking-tour-march-table";
import { HikingTourPrintModal } from "@/components/wanderplaner/hiking-tour-print-modal";
import { useHikingTourData } from "@/components/wanderplaner/use-hiking-tour-data";
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { toIntlLocale } from "@/lib/utils/format";
import {
  ElevationProfilePoint,
  HikingTour,
  HikingTourRoutingProfile,
  HikingTourWaypoint,
  HikingTourWaypointKind,
  HikingTourWaypointVerificationStatus,
} from "@/types/api";

// Auftrag Abschnitt 17 - dieselbe feste Item-Liste wie RECONNAISSANCE_CHECKLIST_ITEMS im
// Backend (app/schemas/hiking_tour.py); Labels unter wanderplaner.detail.reconnaissanceModal.checklist.
const RECONNAISSANCE_CHECKLIST_ITEMS = [
  "trail_condition",
  "problem_spots",
  "exits",
  "access_roads",
  "water_points",
  "alternative_route",
  "decision_points",
] as const;

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  draft: "neutral",
  analyzed: "info",
  reconnoitered: "warning",
  approved: "success",
};

const ROUTING_PROFILES: HikingTourRoutingProfile[] = ["wanderwege_bevorzugen", "schnellste_route", "einfache_route"];

type EditFormState = { title: string; description: string; tour_date: string };
type TFunc = (key: string, values?: Record<string, string | number>) => string;

function formatDistance(t: TFunc, meters: number | null): string {
  if (meters === null) return "–";
  return meters >= 1000
    ? t("units.km", { value: (meters / 1000).toFixed(1) })
    : t("units.meters", { value: String(Math.round(meters)) });
}

export function HikingTourDetail({ initialTour, canWrite }: { initialTour: HikingTour; canWrite: boolean }) {
  const t = useTranslations("wanderplaner");
  const locale = useLocale();
  const intlLocale = toIntlLocale(locale);
  const kindLabel = (kind: HikingTourWaypointKind) => t(`kind.${kind}`);
  const formatTimestampDate = (value: string) => new Date(value).toLocaleDateString(intlLocale);
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>;
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
  const [savingRoute, setSavingRoute] = useState(false);
  const [draftWaypoints, setDraftWaypoints] = useState(initialTour.waypoints);
  const [marchTableRevision, setMarchTableRevision] = useState(0);
  const { elevationProfile, terrainDanger, marchTable } = useHikingTourData(tour, marchTableRevision);
  const [hoveredPoint, setHoveredPoint] = useState<ElevationProfilePoint | null>(null);
  const [showReconnaissance, setShowReconnaissance] = useState(false);
  const [checklistDraft, setChecklistDraft] = useState<Record<string, boolean>>(tour.reconnaissance_checklist);
  const [remarksDraft, setRemarksDraft] = useState(tour.reconnaissance_remarks ?? "");
  const [savingReconnaissance, setSavingReconnaissance] = useState(false);
  const [approving, setApproving] = useState(false);
  const [showPrint, setShowPrint] = useState(false);

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
      showToast(t("detail.toast.saved"), "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : t("detail.toast.saveError"), "error");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteTour() {
    if (!(await confirm({ message: t("detail.confirm.deleteTour", { title: tour.title }), tone: "danger", confirmLabel: t("actions.delete") }))) return;
    try {
      await browserApiFetch(`/api/hiking-tours/${tour.id}`, { method: "DELETE" });
      showToast(t("detail.toast.deleted"), "success");
      router.push("/hiking-planner");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : t("detail.toast.deleteError"), "error");
    }
  }

  const handleMapClick = useCallback((lat: number, lon: number) => {
    if (!placingVia || savingRoute) return;
    setPlacingVia(false);
    const now = new Date().toISOString();
    setDraftWaypoints((previous) => {
      const end = previous.find((waypoint) => waypoint.kind === "END");
      const sequence = end?.sequence ?? previous.length;
      return [...previous.map((waypoint) => waypoint.kind === "END" ? { ...waypoint, sequence: sequence + 1 } : waypoint), {
        id: `draft-${crypto.randomUUID()}`, sequence, kind: "USER_DEFINED" as const, label: null,
        description: null, lat, lon, elevation_m: null, break_minutes: null, break_reason: null,
        auto_generated: false, verification_status: null, decision_metrics_json: null, exit_metrics_json: null,
        created_at: now, updated_at: now,
      }].sort((a, b) => a.sequence - b.sequence);
    });
  }, [placingVia, savingRoute]);

  const handleMarkerDragEnd = useCallback((waypointId: string, lat: number, lon: number) => {
    if (savingRoute) return;
    setDraftWaypoints((previous) => previous.map((waypoint) => waypoint.id === waypointId ? { ...waypoint, lat, lon } : waypoint));
  }, [savingRoute]);

  async function handleDeleteWaypoint(waypoint: HikingTourWaypoint) {
    if (savingRoute || waypoint.kind === "START" || waypoint.kind === "END") return;
    if (!(await confirm({ message: t("detail.confirm.removeWaypoint", { label: waypoint.label ?? kindLabel(waypoint.kind) }), tone: "danger", confirmLabel: t("actions.remove") }))) return;
    setDraftWaypoints((previous) => previous.filter((point) => point.id !== waypoint.id));
  }

  function handleUpdateBreakMinutes(waypoint: HikingTourWaypoint, minutes: number) {
    if (savingRoute) return;
    setDraftWaypoints((previous) => previous.map((point) => point.id === waypoint.id ? { ...point, break_minutes: minutes } : point));
  }

  const changes = useMemo(() => {
    const saved = new Map(tour.waypoints.map((waypoint) => [waypoint.id, waypoint]));
    const updates = draftWaypoints.flatMap((waypoint) => {
      const original = saved.get(waypoint.id);
      if (!original) return [];
      const positionChanged = waypoint.lat !== original.lat || waypoint.lon !== original.lon;
      const pauseChanged = waypoint.break_minutes !== original.break_minutes;
      if (!positionChanged && !pauseChanged) return [];
      return [{ id: waypoint.id,
        ...(positionChanged ? { lat: waypoint.lat, lon: waypoint.lon } : {}),
        ...(pauseChanged ? { break_minutes: waypoint.break_minutes } : {}),
      }];
    });
    return {
      updates,
      additions: draftWaypoints.filter((waypoint) => !saved.has(waypoint.id)).map(({ lat, lon, label, description, break_minutes }) => ({ lat, lon, label, description, break_minutes })),
      deletions: tour.waypoints.filter((waypoint) => !draftWaypoints.some((draft) => draft.id === waypoint.id)).map((waypoint) => waypoint.id),
    };
  }, [draftWaypoints, tour.waypoints]);
  const routeDirty = Boolean(changes.updates.length || changes.additions.length || changes.deletions.length || profile !== (tour.routing_profile ?? "wanderwege_bevorzugen"));
  const needsPlanning = !tour.route_legs.length || !tour.elevation_profile_fetched_at || tour.status === "draft";

  async function handleSaveRoute() {
    if (savingRoute) return;
    setSavingRoute(true);
    setPlacingVia(false);
    try {
      const updated = await browserApiFetch<HikingTour>(`/api/hiking-tours/${tour.id}/plan`, {
        method: "POST",
        body: JSON.stringify({ ...changes, routing_profile: profile, expected_updated_at: tour.updated_at }),
        signal: AbortSignal.timeout(600_000),
      });
      setTour(updated);
      setDraftWaypoints(updated.waypoints);
      setProfile(updated.routing_profile ?? "wanderwege_bevorzugen");
      setHoveredPoint(null);
      setMarchTableRevision((value) => value + 1);
      showToast(t("detail.toast.routeSaved"), "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : t("detail.toast.routeSaveError"), "error");
    } finally {
      setSavingRoute(false);
    }
  }

  async function handleVerificationChange(waypoint: HikingTourWaypoint, status: HikingTourWaypointVerificationStatus) {
    try {
      const updated = await browserApiFetch<HikingTourWaypoint>(`/api/hiking-tours/${tour.id}/waypoints/${waypoint.id}/verification`, {
        method: "PATCH",
        body: JSON.stringify({ verification_status: status }),
      });
      setTour((prev) => ({ ...prev, waypoints: prev.waypoints.map((wp) => (wp.id === updated.id ? updated : wp)) }));
      setDraftWaypoints((previous) => previous.map((waypoint) => waypoint.id === updated.id ? { ...waypoint, verification_status: updated.verification_status } : waypoint));
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : t("detail.toast.verificationError"), "error");
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
      showToast(t("detail.toast.reconnaissanceSaved"), "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : t("detail.toast.reconnaissanceError"), "error");
    } finally {
      setSavingReconnaissance(false);
    }
  }

  async function handleApprove() {
    if (!(await confirm({ message: t("detail.confirm.approveTour", { title: tour.title }), confirmLabel: t("detail.approve") }))) return;
    setApproving(true);
    try {
      const updated = await browserApiFetch<HikingTour>(`/api/hiking-tours/${tour.id}/approve`, { method: "POST" });
      setTour((prev) => ({ ...updated, route_legs: prev.route_legs }));
      showToast(t("detail.toast.approved"), "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : t("detail.toast.approveError"), "error");
    } finally {
      setApproving(false);
    }
  }

  const mapWaypoints = useMemo(
    () => draftWaypoints.map((wp) => ({ id: wp.id, kind: wp.kind, lat: wp.lat, lon: wp.lon, label: wp.label, description: wp.description, elevation_m: wp.elevation_m, break_minutes: wp.break_minutes })),
    [draftWaypoints]
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
          <p className="muted">{tour.description || t("detail.noDescription")}</p>
          <Badge variant={STATUS_VARIANT[tour.status] ?? "neutral"}>{STATUS_VARIANT[tour.status] ? t(`status.${tour.status}`) : tour.status}</Badge>
        </div>
        {canWrite && (
          <div className="page-header-actions">
            <button type="button" className="button-secondary" onClick={() => setShowEdit(true)} disabled={savingRoute}>
              {t("detail.edit")}
            </button>
            <button type="button" className="button-secondary" onClick={() => setShowReconnaissance(true)} disabled={savingRoute}>
              {t("detail.reconnaissance")}
            </button>
            {tour.route_legs.length > 0 && (
              <button type="button" className="button-secondary" onClick={() => setShowPrint(true)} disabled={savingRoute}>
                {t("detail.print")}
              </button>
            )}
            {tour.route_legs.length > 0 && (
              <a className="button-secondary" href={`/api/hiking-tours/${tour.id}/gpx`}>
                {t("detail.exportGpx")}
              </a>
            )}
            {tour.status === "reconnoitered" && (
              <button type="button" className="button-primary" onClick={() => void handleApprove()} disabled={approving || savingRoute}>
                {approving ? t("detail.approving") : t("detail.approve")}
              </button>
            )}
            <button type="button" className="button-danger" onClick={() => void handleDeleteTour()} disabled={savingRoute}>
              {t("actions.delete")}
            </button>
          </div>
        )}
      </div>

      <div className="section-card">
        <DataToolbar
          title={t("detail.route.title")}
          description={t("detail.route.description")}
          actions={
            canWrite ? (
              <div className="page-header-actions">
                <Select aria-label={t("detail.route.routingProfile")} disabled={savingRoute} value={profile} onChange={(event) => setProfile(event.target.value as HikingTourRoutingProfile)}>
                  {ROUTING_PROFILES.map((value) => (
                    <option key={value} value={value}>
                      {t(`routingProfile.${value}`)}
                    </option>
                  ))}
                </Select>
                {(routeDirty || needsPlanning || savingRoute) && (
                  <button type="button" className="button-primary wanderplaner-loading-button" onClick={() => void handleSaveRoute()} disabled={savingRoute} aria-busy={savingRoute}>
                    {savingRoute && <HikingTourLoadingLandscape />}
                    <span className="wanderplaner-loading-label">{savingRoute ? t("detail.route.savingAndCalculating") : t("actions.save")}</span>
                  </button>
                )}
                {routeDirty && !savingRoute && (
                  <button type="button" className="button-ghost" onClick={() => {
                    setDraftWaypoints(tour.waypoints);
                    setProfile(tour.routing_profile ?? "wanderwege_bevorzugen");
                    setPlacingVia(false);
                  }}>{t("detail.route.discardChanges")}</button>
                )}
                <button
                  type="button"
                  className={placingVia ? "button-toggle button-toggle-active" : "button-toggle"}
                  disabled={savingRoute}
                  onClick={() => setPlacingVia((value) => !value)}
                >
                  {t("detail.route.addVia")}
                </button>
              </div>
            ) : undefined
          }
        />
        {routeDirty && <p className="field-help">{t("detail.route.unsavedHint")}</p>}
        {(routeDirty || needsPlanning) && <p className="field-help">{t("detail.route.swisstopoHint")}</p>}
        {placingVia && <p className="field-help">{t("detail.route.placeViaHint")}</p>}
        <HikingTourMap
          waypoints={mapWaypoints}
          routeCoordinates={routeCoordinates}
          elevationProfile={elevationProfile?.points}
          dangerSegments={terrainDanger?.segments}
          onMapClick={canWrite && !savingRoute ? handleMapClick : undefined}
          onMarkerDragEnd={canWrite && !savingRoute ? handleMarkerDragEnd : undefined}
          highlightPoint={hoveredPoint ? { lat: hoveredPoint.lat, lon: hoveredPoint.lon } : null}
        />
        {tour.route_distance_m !== null && tour.route_distance_m !== undefined && (
          <div className="wanderplaner-route-summary">
            <span>{t.rich("detail.route.distance", { value: formatDistance(t, tour.route_distance_m), strong })}</span>
            <span>{t.rich("detail.route.ascent", { value: t("units.meters", { value: String(Math.round(tour.route_ascent_m ?? 0)) }), strong })}</span>
            <span>{t.rich("detail.route.descent", { value: t("units.meters", { value: String(Math.round(tour.route_descent_m ?? 0)) }), strong })}</span>
          </div>
        )}
      </div>

      {tour.route_legs.length > 0 && (
        <div className="section-card">
          <DataToolbar
            title={t("detail.elevation.title")}
            description={t("detail.elevation.description")}
          />
          {elevationProfile ? (
            <HikingTourElevationChart points={elevationProfile.points} waypoints={tour.waypoints} marchTable={marchTable} onHoverPoint={setHoveredPoint} dangerSegments={terrainDanger?.segments} />
          ) : (
            <p className="field-help">{t("detail.elevation.empty")}</p>
          )}
        </div>
      )}

      <div className="section-card">
        <HikingTourMarchTable
          table={marchTable}
          waypoints={draftWaypoints}
          canWrite={canWrite && !savingRoute}
          dangerSegments={terrainDanger?.segments}
          onUpdateBreakMinutes={handleUpdateBreakMinutes}
          onVerificationChange={(waypoint, status) => void handleVerificationChange(waypoint, status)}
          onDeleteWaypoint={(waypoint) => void handleDeleteWaypoint(waypoint)}
        />
      </div>

      <Modal open={showEdit} title={t("detail.editModal.title")} onClose={() => setShowEdit(false)}>
        <form onSubmit={(event) => void handleEditSave(event)}>
          <div className="grid">
            <label className="field-stack">
              <span className="field-label">{t("fields.title")}</span>
              <input required value={editForm.title} onChange={(event) => setEditForm({ ...editForm, title: event.target.value })} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("fields.description")}</span>
              <textarea rows={3} value={editForm.description} onChange={(event) => setEditForm({ ...editForm, description: event.target.value })} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("fields.date")}</span>
              <DateInput value={editForm.tour_date} onChange={(value) => setEditForm({ ...editForm, tour_date: value })} />
            </label>
          </div>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setShowEdit(false)}>
              {t("actions.cancel")}
            </button>
            <button type="submit" className="button-primary" disabled={saving}>
              {saving ? t("actions.saving") : t("actions.save")}
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={showReconnaissance}
        title={t("detail.reconnaissance")}
        onClose={() => setShowReconnaissance(false)}
      >
        <form onSubmit={(event) => void handleSaveReconnaissance(event)}>
          <div className="grid">
            {(tour.reconnoitered_at || tour.approved_at) && (
              <p className="muted">
                {tour.reconnoitered_at && (
                  <>
                    {tour.reconnoitered_by_name
                      ? t("detail.reconnaissanceModal.reconnoiteredByOn", { name: tour.reconnoitered_by_name, date: formatTimestampDate(tour.reconnoitered_at) })
                      : t("detail.reconnaissanceModal.reconnoiteredOn", { date: formatTimestampDate(tour.reconnoitered_at) })}{" "}
                  </>
                )}
                {tour.approved_at && (tour.approved_by_name
                  ? t("detail.reconnaissanceModal.approvedByOn", { name: tour.approved_by_name, date: formatTimestampDate(tour.approved_at) })
                  : t("detail.reconnaissanceModal.approvedOn", { date: formatTimestampDate(tour.approved_at) }))}
              </p>
            )}
            <div className="grid">
              {RECONNAISSANCE_CHECKLIST_ITEMS.map((key) => (
                <label key={key} className="mini-menu-option">
                  <span>{t(`detail.reconnaissanceModal.checklist.${key}`)}</span>
                  <input
                    type="checkbox"
                    checked={checklistDraft[key] ?? false}
                    onChange={(event) => setChecklistDraft((prev) => ({ ...prev, [key]: event.target.checked }))}
                  />
                </label>
              ))}
            </div>
            <label className="field-stack">
              <span className="field-label">{t("detail.reconnaissanceModal.remarks")}</span>
              <textarea rows={3} value={remarksDraft} onChange={(event) => setRemarksDraft(event.target.value)} />
            </label>
          </div>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setShowReconnaissance(false)}>
              {t("actions.cancel")}
            </button>
            <button type="submit" className="button-primary" disabled={savingReconnaissance}>
              {savingReconnaissance ? t("actions.saving") : t("detail.reconnaissanceModal.submit")}
            </button>
          </div>
        </form>
      </Modal>

      <HikingTourPrintModal tourId={tour.id} open={showPrint} onClose={() => setShowPrint(false)} />
    </div>
  );
}
