"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { CSSProperties, FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { MobileIcon } from "@/components/mobile/mobile-icons";
import { MobileEmpty, MobileSegmented } from "@/components/mobile/mobile-ui";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatWeekdayDate, toIntlLocale } from "@/lib/utils/format";
import {
  HikingTour,
  HikingTourRoutingProfile,
  HikingTourWaypoint,
  HikingTourWaypointKind,
  HikingTourWaypointVerificationStatus,
  MarchTimeEntry,
} from "@/types/api";

import { KIND_COLOR_TOKEN, HikingTourMap, MapUserPosition } from "./hiking-tour-map";
import { exitSourceSequence, formatHm, formatMinutes, orderWaypoints, rowDanger } from "./hiking-tour-march-table";
import { HikingTourPrintModal } from "./hiking-tour-print-modal";
import { HikingTourProfileStrip } from "./hiking-tour-profile-strip";
import {
  buildTrack,
  clockMinutes,
  dangerAhead,
  dangerLengths,
  elevationAt,
  formatClock,
  plannedMinutesAt,
  projectOnTrack,
  remainingAscent,
  trackLength,
} from "./hiking-tour-route-geometry";
import { useHikingTourData } from "./use-hiking-tour-data";

// Mobile-Ansicht einer Tour (Design "hocX Wanderplaner Mobile v2"): Übersicht mit Karte und
// Bottom-Sheet, Marschtabelle als Zeitleiste, Live-Navigation und Rekognoszierung. Die Ansicht
// steht als ?view=… in der URL, damit die Zurück-Taste des Handys zur Übersicht führt.

type View = "overview" | "table" | "nav" | "reko";
const VIEWS: Record<Exclude<View, "overview">, string> = { table: "march-table", nav: "navigation", reko: "reconnaissance" };

// Dieselbe feste Liste wie RECONNAISSANCE_CHECKLIST_ITEMS im Backend (app/schemas/hiking_tour.py).
const RECONNAISSANCE_CHECKLIST_ITEMS = [
  "trail_condition",
  "problem_spots",
  "exits",
  "access_roads",
  "water_points",
  "alternative_route",
  "decision_points",
] as const;

const ROUTING_PROFILES: HikingTourRoutingProfile[] = ["wanderwege_bevorzugen", "schnellste_route", "einfache_route"];

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  draft: "neutral",
  analyzed: "info",
  reconnoitered: "warning",
  approved: "success",
};

const VERIFICATION_VARIANT: Record<HikingTourWaypointVerificationStatus, BadgeVariant> = {
  AUTO_DETECTED: "info",
  NEEDS_VERIFICATION: "warning",
  VERIFIED: "success",
  REJECTED: "danger",
};

/** Abweichung von der Route, ab der die Navigation warnt (GPS-Genauigkeit im Wald ~20-40 m). */
const OFF_ROUTE_M = 60;

type TFunc = (key: string, values?: Record<string, string | number>) => string;

function distanceLabel(t: TFunc, meters: number): string {
  if (meters >= 1000) return t("units.km", { value: (meters / 1000).toFixed(1) });
  return t("units.meters", { value: String(Math.max(0, Math.round(meters / 10) * 10)) });
}

function effectiveVerification(waypoint: HikingTourWaypoint): HikingTourWaypointVerificationStatus | null {
  return waypoint.verification_status ?? (waypoint.auto_generated ? "AUTO_DETECTED" : null);
}

function isUnverified(waypoint: HikingTourWaypoint): boolean {
  const status = effectiveVerification(waypoint);
  return status === "AUTO_DETECTED" || status === "NEEDS_VERIFICATION";
}

function KindDot({ kind, glyph, unverified = false, size = "md" }: { kind: HikingTourWaypointKind; glyph: string; unverified?: boolean; size?: "sm" | "md" }) {
  return (
    <span
      className={`wanderplaner-m-kind wanderplaner-m-kind-${size}${unverified ? " wanderplaner-m-kind-unverified" : ""}`}
      style={{ "--wanderplaner-marker-color": `var(${KIND_COLOR_TOKEN[kind] ?? "--accent"})` } as CSSProperties}
      aria-hidden="true"
    >
      {glyph}
    </span>
  );
}

function ScreenHeader({ title, onBack, backLabel, trailing }: { title: string; onBack: () => void; backLabel: string; trailing?: ReactNode }) {
  return (
    <div className="wanderplaner-m-header">
      <button type="button" className="wanderplaner-m-round" aria-label={backLabel} onClick={onBack}>
        <MobileIcon name="chevronLeft" size={20} strokeWidth={2.2} />
      </button>
      <h1 className="wanderplaner-m-header-title">{title}</h1>
      <span className="wanderplaner-m-header-trailing">{trailing}</span>
    </div>
  );
}

export function HikingTourMobile({ initialTour, canWrite }: { initialTour: HikingTour; canWrite: boolean }) {
  const t = useTranslations("wanderplaner");
  const locale = useLocale();
  const intlLocale = toIntlLocale(locale);
  const router = useRouter();
  const searchParams = useSearchParams();
  const confirm = useConfirm();
  const showToast = useToast();
  const [tour, setTour] = useState(initialTour);
  const [marchTableRevision, setMarchTableRevision] = useState(0);
  const { elevationProfile, terrainDanger, marchTable } = useHikingTourData(tour, marchTableRevision);
  const [showPrint, setShowPrint] = useState(false);
  const [recalculating, setRecalculating] = useState(false);

  const kindLabel = useCallback((kind: HikingTourWaypointKind) => t(`kind.${kind}`), [t]);
  const glyph = (kind: HikingTourWaypointKind) => kindLabel(kind).charAt(0).toUpperCase();
  const duration = (minutes: number) => formatMinutes(t, minutes);
  const distance = (meters: number) => distanceLabel(t, meters);

  // ── Ansicht über ?view=… (Zurück-Taste) ───────────────────────────
  const viewParam = searchParams.get("view");
  const view: View = (Object.entries(VIEWS).find(([, value]) => value === viewParam)?.[0] as View | undefined) ?? "overview";
  const pushedViewRef = useRef(false);
  const openView = (next: Exclude<View, "overview">) => {
    pushedViewRef.current = true;
    window.history.pushState(null, "", `?view=${VIEWS[next]}`);
  };
  const closeView = () => {
    if (pushedViewRef.current) {
      pushedViewRef.current = false;
      window.history.back();
    } else {
      window.history.replaceState(null, "", window.location.pathname);
    }
  };

  const routeCoordinates = useMemo<[number, number][]>(() => tour.route_legs.flatMap((leg) => leg.coordinates), [tour.route_legs]);
  const hasRoute = routeCoordinates.length > 1;
  const orderedWaypoints = useMemo(() => orderWaypoints(tour.waypoints), [tour.waypoints]);
  const entryFor = useMemo(() => {
    const entries = new Map(marchTable?.entries.map((entry) => [entry.sequence, entry]) ?? []);
    return (waypoint: HikingTourWaypoint): MarchTimeEntry | undefined => {
      const candidate = entries.get(waypoint.sequence);
      return candidate?.kind === waypoint.kind ? candidate : undefined;
    };
  }, [marchTable]);
  const mapWaypoints = useMemo(
    () => tour.waypoints
      .filter((waypoint) => effectiveVerification(waypoint) !== "REJECTED")
      .map((waypoint) => ({ id: waypoint.id, kind: waypoint.kind, lat: waypoint.lat, lon: waypoint.lon, label: waypoint.label, description: waypoint.description, elevation_m: waypoint.elevation_m, break_minutes: waypoint.break_minutes, unverified: isUnverified(waypoint) })),
    [tour.waypoints]
  );
  const lengths = dangerLengths(terrainDanger?.segments);
  const elevations = elevationProfile?.points.map((point) => point.elevation_m) ?? [];
  const lastEntry = marchTable?.entries.filter((entry) => entry.kind !== "EMERGENCY_EXIT").at(-1);
  const startClock = clockMinutes(tour.planned_start_time);

  async function handleRoutingProfile(next: HikingTourRoutingProfile) {
    if (!canWrite || recalculating || next === (tour.routing_profile ?? "wanderwege_bevorzugen")) return;
    setRecalculating(true);
    try {
      const updated = await browserApiFetch<HikingTour>(`/api/hiking-tours/${tour.id}/plan`, {
        method: "POST",
        body: JSON.stringify({ updates: [], additions: [], deletions: [], routing_profile: next, expected_updated_at: tour.updated_at }),
        signal: AbortSignal.timeout(600_000),
      });
      setTour(updated);
      setMarchTableRevision((value) => value + 1);
      showToast(t("detail.toast.routeSaved"), "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : t("detail.toast.routeSaveError"), "error");
    } finally {
      setRecalculating(false);
    }
  }

  // ── Rekognoszierung ───────────────────────────────────────────────
  const [checklistDraft, setChecklistDraft] = useState<Record<string, boolean>>(tour.reconnaissance_checklist);
  const [remarksDraft, setRemarksDraft] = useState(tour.reconnaissance_remarks ?? "");
  const [savingReconnaissance, setSavingReconnaissance] = useState(false);
  const [approving, setApproving] = useState(false);
  const reconnaissanceDirty = remarksDraft !== (tour.reconnaissance_remarks ?? "")
    || RECONNAISSANCE_CHECKLIST_ITEMS.some((key) => Boolean(checklistDraft[key]) !== Boolean(tour.reconnaissance_checklist[key]));
  const reconnaissanceLocked = !canWrite || tour.status === "approved";
  const verifyWaypoints = orderedWaypoints.filter((waypoint) => effectiveVerification(waypoint) !== null);
  const openVerifications = verifyWaypoints.filter(isUnverified).length;
  const checkedCount = RECONNAISSANCE_CHECKLIST_ITEMS.filter((key) => checklistDraft[key]).length;

  async function handleVerificationChange(waypoint: HikingTourWaypoint, status: HikingTourWaypointVerificationStatus) {
    try {
      const updated = await browserApiFetch<HikingTourWaypoint>(`/api/hiking-tours/${tour.id}/waypoints/${waypoint.id}/verification`, {
        method: "PATCH",
        body: JSON.stringify({ verification_status: status }),
      });
      setTour((prev) => ({ ...prev, waypoints: prev.waypoints.map((wp) => (wp.id === updated.id ? updated : wp)) }));
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

  // ── Live-Navigation ───────────────────────────────────────────────
  const [tracking, setTracking] = useState(false);
  const [fix, setFix] = useState<{ lat: number; lon: number; accuracy: number; heading: number | null; altitude: number | null } | null>(null);
  const [geoError, setGeoError] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [exitOpen, setExitOpen] = useState(false);
  const [focusPoint, setFocusPoint] = useState<{ lat: number; lon: number } | null>(null);
  const [navStartedAt, setNavStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (view !== "nav" || !tracking) return;
    if (!("geolocation" in navigator)) {
      setGeoError("unsupported");
      setTracking(false);
      return;
    }
    const watchId = navigator.geolocation.watchPosition(
      (position) => {
        setGeoError(null);
        setFix({
          lat: position.coords.latitude,
          lon: position.coords.longitude,
          accuracy: position.coords.accuracy,
          heading: position.coords.heading,
          altitude: position.coords.altitude,
        });
        setNow(Date.now());
      },
      (error) => setGeoError(error.code === error.PERMISSION_DENIED ? "denied" : "unavailable"),
      { enableHighAccuracy: true, maximumAge: 5_000, timeout: 30_000 }
    );
    // Bildschirm während der Navigation anlassen (best effort, nicht jeder Browser kann es).
    let wakeLock: { release: () => Promise<void> } | null = null;
    const wakeLockApi = (navigator as Navigator & { wakeLock?: { request: (type: "screen") => Promise<{ release: () => Promise<void> }> } }).wakeLock;
    wakeLockApi?.request("screen").then((lock) => { wakeLock = lock; }).catch(() => {});
    const clock = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => {
      navigator.geolocation.clearWatch(watchId);
      window.clearInterval(clock);
      void wakeLock?.release().catch(() => {});
    };
  }, [view, tracking]);

  useEffect(() => {
    if (view !== "nav") setTracking(false);
  }, [view]);

  function startNavigation() {
    setTracking(true);
    setFollow(true);
    setExitOpen(false);
    setFocusPoint(null);
    setNavStartedAt(Date.now());
    openView("nav");
  }

  function endNavigation() {
    setTracking(false);
    setFix(null);
    setNavStartedAt(null);
    setExitOpen(false);
    closeView();
  }

  const track = useMemo(() => buildTrack(elevationProfile?.points, routeCoordinates), [elevationProfile, routeCoordinates]);
  const totalM = trackLength(track) || tour.route_distance_m || 0;
  const projection = fix ? projectOnTrack(track, fix.lat, fix.lon) : null;
  const alongM = projection?.distance_m ?? null;
  const routeDistanceOf = useCallback((waypoint: HikingTourWaypoint) => {
    const entry = entryFor(waypoint);
    if (entry) return entry.cumulative_distance_m;
    return projectOnTrack(track, waypoint.lat, waypoint.lon)?.distance_m ?? 0;
  }, [entryFor, track]);
  const routeWaypoints = orderedWaypoints.filter((waypoint) => waypoint.kind !== "EMERGENCY_EXIT" && effectiveVerification(waypoint) !== "REJECTED");
  const nextWaypoint = alongM === null ? null : routeWaypoints.find((waypoint) => waypoint.kind !== "START" && routeDistanceOf(waypoint) > alongM + 15) ?? null;
  const arrived = alongM !== null && totalM > 0 && alongM >= totalM - 30;
  const danger = alongM === null ? null : dangerAhead(terrainDanger?.segments, alongM);
  const plannedNow = alongM !== null && marchTable ? plannedMinutesAt(marchTable.entries, alongM) : null;
  const nowDate = new Date(now);
  const nowClock = nowDate.getHours() * 60 + nowDate.getMinutes();
  const isTourDay = tour.tour_date === `${nowDate.getFullYear()}-${String(nowDate.getMonth() + 1).padStart(2, "0")}-${String(nowDate.getDate()).padStart(2, "0")}`;
  const scheduleDelta = isTourDay && startClock !== null && plannedNow !== null ? Math.round(nowClock - (startClock + plannedNow)) : null;
  const remainingPlanned = marchTable && plannedNow !== null ? Math.max(0, marchTable.summary.total_duration_minutes - plannedNow) : null;

  const exits = orderedWaypoints.filter((waypoint) => waypoint.kind === "EMERGENCY_EXIT" && effectiveVerification(waypoint) !== "REJECTED");
  const exitAlong = (exit: HikingTourWaypoint) => {
    const source = tour.waypoints.find((waypoint) => waypoint.sequence === exitSourceSequence(exit) && waypoint.kind !== "EMERGENCY_EXIT");
    return source ? routeDistanceOf(source) : (projectOnTrack(track, exit.lat, exit.lon)?.distance_m ?? 0);
  };
  const nearestExit = exits.length
    ? exits.reduce((best, exit) => (Math.abs(exitAlong(exit) - (alongM ?? 0)) < Math.abs(exitAlong(best) - (alongM ?? 0)) ? exit : best))
    : null;

  let navWarning: { tone: "steep_exposed" | "alpine" | "off"; title: string; text: string } | null = null;
  if (projection && projection.offset_m > OFF_ROUTE_M) {
    navWarning = { tone: "off", title: t("mobile.nav.offRoute.title"), text: t("mobile.nav.offRoute.text", { distance: distance(projection.offset_m) }) };
  } else if (danger?.state === "inside") {
    navWarning = { tone: danger.danger, title: t("mobile.nav.dangerInside.title", { label: t(`danger.${danger.danger}.label`) }), text: t("mobile.nav.dangerInside.text", { distance: distance(danger.remaining_m) }) };
  } else if (danger?.state === "ahead") {
    navWarning = { tone: danger.danger, title: t("mobile.nav.dangerAhead.title", { distance: distance(danger.distance_m), label: t(`danger.${danger.danger}.label`) }), text: t("mobile.nav.dangerAhead.text", { length: distance(danger.length_m), description: t(`danger.${danger.danger}.description`) }) };
  }

  const userPosition = useMemo<MapUserPosition | null>(() => (fix ? { lat: fix.lat, lon: fix.lon, heading: fix.heading } : null), [fix]);
  const backLabel = t("mobile.back");

  // ── Darstellung ───────────────────────────────────────────────────
  const metaParts = [
    tour.tour_date ? formatWeekdayDate(tour.tour_date, locale) : null,
    tour.planned_start_time ? t("mobile.startAt", { time: formatHm(tour.planned_start_time) }) : null,
  ].filter(Boolean);

  const profileLegend = elevationProfile && elevations.length > 0 && (
    <div className="wanderplaner-m-legend">
      {lengths.steep_exposed > 0 && (
        <span><span className="wanderplaner-m-swatch wanderplaner-m-swatch-steep_exposed" aria-hidden="true" />{t("mobile.dangerLength", { label: t("danger.steep_exposed.label"), length: distance(lengths.steep_exposed) })}</span>
      )}
      {lengths.alpine > 0 && (
        <span><span className="wanderplaner-m-swatch wanderplaner-m-swatch-alpine" aria-hidden="true" />{t("mobile.dangerLength", { label: t("danger.alpine.label"), length: distance(lengths.alpine) })}</span>
      )}
      <span>{t("mobile.elevationRange", { low: String(Math.round(Math.min(...elevations))), high: String(Math.round(Math.max(...elevations))) })}</span>
    </div>
  );

  if (view === "table") {
    return (
      <div className="wanderplaner-m-page">
        <ScreenHeader
          title={t("marchTable.title")}
          onBack={closeView}
          backLabel={backLabel}
          trailing={hasRoute && canWrite ? <button type="button" className="wanderplaner-m-pill-button" onClick={() => setShowPrint(true)}>{t("mobile.actions.print")}</button> : null}
        />
        <div className="wanderplaner-m-meta-grid">
          {tour.tour_date && <div className="wanderplaner-m-meta"><span>{t("fields.date")}</span><strong>{formatWeekdayDate(tour.tour_date, locale)}</strong></div>}
          {tour.planned_start_time && <div className="wanderplaner-m-meta"><span>{t("mobile.table.start")}</span><strong>{formatHm(tour.planned_start_time)}</strong></div>}
          {marchTable && <div className="wanderplaner-m-meta"><span>{t("mobile.table.speed")}</span><strong>{t("mobile.table.kmh", { value: marchTable.speed_factor_kmh.toLocaleString(intlLocale) })}</strong></div>}
          {marchTable && <div className="wanderplaner-m-meta"><span>{t("mobile.table.breaks")}</span><strong>{duration(marchTable.summary.break_duration_minutes)}</strong></div>}
        </div>
        {!marchTable ? (
          <MobileEmpty title={t("marchTable.noRoute")} />
        ) : (
          <ol className="wanderplaner-m-timeline">
            {orderedWaypoints.map((waypoint, index) => {
              const entry = entryFor(waypoint);
              const verification = effectiveVerification(waypoint);
              const nextEntry = orderedWaypoints.slice(index + 1).map(entryFor).find(Boolean);
              const legDanger = rowDanger(nextEntry, terrainDanger?.segments);
              const last = index === orderedWaypoints.length - 1;
              const metrics = waypoint.decision_metrics_json;
              const note = waypoint.description || entry?.remarks;
              return (
                <li key={waypoint.id} className="wanderplaner-m-row">
                  <span className="wanderplaner-m-row-time">{formatHm(entry?.planned_arrival ?? null)}</span>
                  <span className="wanderplaner-m-row-rail">
                    <KindDot kind={waypoint.kind} glyph={glyph(waypoint.kind)} unverified={isUnverified(waypoint)} />
                    {!last && <span className={`wanderplaner-m-row-line${legDanger ? ` wanderplaner-m-row-line-${legDanger}` : ""}`} />}
                  </span>
                  <div className="wanderplaner-m-row-body">
                    <div className="wanderplaner-m-row-title">
                      <strong>{waypoint.label || kindLabel(waypoint.kind)}</strong>
                      {verification && <Badge variant={VERIFICATION_VARIANT[verification]}>{t(`verification.${verification}`)}</Badge>}
                    </div>
                    <span className="wanderplaner-m-muted">
                      {entry && entry.segment_distance_m > 0
                        ? t("mobile.table.leg", { kind: kindLabel(waypoint.kind), distance: distance(entry.segment_distance_m), ascent: String(Math.round(entry.segment_ascent_m)), lkm: entry.segment_lkm.toFixed(1) })
                        : kindLabel(waypoint.kind)}
                      {entry && entry.break_minutes > 0 ? ` · ${t("mobile.table.break", { minutes: String(entry.break_minutes) })}` : ""}
                    </span>
                    {legDanger && !last && (
                      <span className={`wanderplaner-m-row-danger wanderplaner-m-row-danger-${legDanger}`}>
                        {t("mobile.table.dangerAfter", { label: t(`danger.${legDanger}.label`) })}
                      </span>
                    )}
                    {(note || metrics) && (
                      <span className="wanderplaner-m-note">
                        {note}
                        {metrics && (
                          <>
                            {note ? " · " : ""}
                            {t("marchTable.decisionMetrics", { fromStart: duration(metrics.time_from_start_minutes), toEnd: duration(metrics.time_to_end_minutes), back: duration(metrics.time_back_minutes) })}
                          </>
                        )}
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
        {marchTable && (
          <div className="wanderplaner-m-totals">
            <div><strong>{t("units.lkm", { value: marchTable.summary.total_lkm.toFixed(1) })}</strong><span>{t("mobile.table.totalsDistance", { distance: distance(marchTable.summary.total_distance_m), ascent: String(Math.round(marchTable.summary.total_ascent_m)) })}</span></div>
            <div><strong>{duration(marchTable.summary.total_duration_minutes)}</strong><span>{t("mobile.table.totalsBreaks", { duration: duration(marchTable.summary.break_duration_minutes) })}</span></div>
            {lastEntry?.planned_arrival && <div><strong>{formatHm(lastEntry.planned_arrival)}</strong><span>{t("mobile.table.arrival")}</span></div>}
          </div>
        )}
        <HikingTourPrintModal tourId={tour.id} open={showPrint} onClose={() => setShowPrint(false)} sheet />
      </div>
    );
  }

  if (view === "reko") {
    return (
      <form className="wanderplaner-m-page" onSubmit={(event) => void handleSaveReconnaissance(event)}>
        <ScreenHeader
          title={t("detail.reconnaissance")}
          onBack={closeView}
          backLabel={backLabel}
          trailing={<span className="wanderplaner-m-count">{t("mobile.reko.count", { done: checkedCount, total: RECONNAISSANCE_CHECKLIST_ITEMS.length })}</span>}
        />
        {tour.status === "approved" && <StatusBanner tone="success" message={t("mobile.reko.approvedLocked")} />}
        <section className="wanderplaner-m-section">
          <span className="mobile-eyebrow">{t("mobile.reko.checked")}</span>
          <div className="wanderplaner-m-checklist">
            {RECONNAISSANCE_CHECKLIST_ITEMS.map((key) => {
              const on = Boolean(checklistDraft[key]);
              return (
                <button
                  key={key}
                  type="button"
                  className={`wanderplaner-m-check${on ? " wanderplaner-m-check-on" : ""}`}
                  aria-pressed={on}
                  disabled={reconnaissanceLocked}
                  onClick={() => setChecklistDraft((prev) => ({ ...prev, [key]: !prev[key] }))}
                >
                  <span className="wanderplaner-m-check-box" aria-hidden="true">{on && <MobileIcon name="check" size={13} strokeWidth={3} />}</span>
                  {t(`detail.reconnaissanceModal.checklist.${key}`)}
                </button>
              );
            })}
          </div>
        </section>
        <section className="wanderplaner-m-section">
          <span className="mobile-eyebrow">{t("mobile.reko.verify")}</span>
          {verifyWaypoints.length === 0 ? (
            <span className="wanderplaner-m-muted">{t("mobile.reko.verifyEmpty")}</span>
          ) : verifyWaypoints.map((waypoint) => {
            const status = effectiveVerification(waypoint) as HikingTourWaypointVerificationStatus;
            return (
              <div key={waypoint.id} className="wanderplaner-m-verify">
                <KindDot kind={waypoint.kind} glyph={glyph(waypoint.kind)} unverified={isUnverified(waypoint)} />
                <span className="wanderplaner-m-verify-text">
                  <strong>{waypoint.label || kindLabel(waypoint.kind)}</strong>
                  <span className={`wanderplaner-m-verify-status wanderplaner-m-verify-status-${VERIFICATION_VARIANT[status]}`}>
                    {kindLabel(waypoint.kind)} · {t(`verification.${status}`)}
                  </span>
                </span>
                {canWrite && (
                  <>
                    <button type="button" className={`wanderplaner-m-verify-button${status === "REJECTED" ? " wanderplaner-m-verify-button-rejected" : ""}`} aria-label={t("mobile.reko.reject", { label: waypoint.label || kindLabel(waypoint.kind) })} aria-pressed={status === "REJECTED"} onClick={() => void handleVerificationChange(waypoint, "REJECTED")}>
                      <MobileIcon name="close" size={16} strokeWidth={2.4} />
                    </button>
                    <button type="button" className={`wanderplaner-m-verify-button${status === "VERIFIED" ? " wanderplaner-m-verify-button-verified" : ""}`} aria-label={t("mobile.reko.confirm", { label: waypoint.label || kindLabel(waypoint.kind) })} aria-pressed={status === "VERIFIED"} onClick={() => void handleVerificationChange(waypoint, "VERIFIED")}>
                      <MobileIcon name="check" size={16} strokeWidth={2.4} />
                    </button>
                  </>
                )}
              </div>
            );
          })}
        </section>
        <label className="field-stack wanderplaner-m-section">
          <span className="field-label">{t("detail.reconnaissanceModal.remarks")}</span>
          <textarea rows={3} value={remarksDraft} disabled={reconnaissanceLocked} onChange={(event) => setRemarksDraft(event.target.value)} />
        </label>
        <div className="wanderplaner-m-footer">
          <span className="wanderplaner-m-muted wanderplaner-m-center">
            {tour.approved_at
              ? (tour.approved_by_name ? t("detail.reconnaissanceModal.approvedByOn", { name: tour.approved_by_name, date: new Date(tour.approved_at).toLocaleDateString(intlLocale) }) : t("detail.reconnaissanceModal.approvedOn", { date: new Date(tour.approved_at).toLocaleDateString(intlLocale) }))
              : openVerifications > 0 ? t("mobile.reko.openPoints", { count: openVerifications }) : t("mobile.reko.allChecked")}
            {!tour.approved_at && tour.reconnoitered_at && tour.reconnoitered_by_name ? ` · ${t("mobile.reko.reconnoiteredBy", { name: tour.reconnoitered_by_name })}` : ""}
          </span>
          {!reconnaissanceLocked && (reconnaissanceDirty || tour.status !== "reconnoitered") && (
            <button type="submit" className="button-primary wanderplaner-m-wide" disabled={savingReconnaissance}>
              {savingReconnaissance ? t("actions.saving") : t("detail.reconnaissanceModal.submit")}
            </button>
          )}
          {canWrite && tour.status === "reconnoitered" && !reconnaissanceDirty && (
            <button type="button" className="button-primary wanderplaner-m-wide" disabled={approving} onClick={() => void handleApprove()}>
              {approving ? t("detail.approving") : t("detail.approve")}
            </button>
          )}
        </div>
      </form>
    );
  }

  const mapBlock = hasRoute ? (
    <HikingTourMap
      variant="mobile"
      waypoints={mapWaypoints}
      routeCoordinates={routeCoordinates}
      elevationProfile={elevationProfile?.points}
      dangerSegments={terrainDanger?.segments}
      fitPadding={view === "nav" ? { top: 220, right: 40, bottom: 360, left: 40 } : { top: 90, right: 40, bottom: 440, left: 40 }}
      userPosition={view === "nav" ? userPosition : null}
      followUser={view === "nav" && follow}
      onUserPan={() => setFollow(false)}
      focusPoint={focusPoint}
    />
  ) : null;

  if (view === "nav") {
    const nextEntry = nextWaypoint ? entryFor(nextWaypoint) : undefined;
    const nextDistance = nextWaypoint && alongM !== null ? routeDistanceOf(nextWaypoint) - alongM : null;
    const exitDelta = nearestExit && alongM !== null ? exitAlong(nearestExit) - alongM : null;
    return (
      <div className="wanderplaner-m-screen">
        {mapBlock}
        <div className="wanderplaner-m-nav-top">
          <div className="wanderplaner-m-nav-card">
            <div className="wanderplaner-m-nav-main">
              <span className="wanderplaner-m-nav-icon" aria-hidden="true"><MobileIcon name={arrived ? "check" : "location"} size={30} strokeWidth={2.2} /></span>
              <span className="wanderplaner-m-nav-text">
                {geoError ? (
                  <strong>{t(`mobile.nav.geoError.${geoError}`)}</strong>
                ) : !fix ? (
                  <strong>{tracking ? t("mobile.nav.searching") : t("mobile.nav.paused")}</strong>
                ) : arrived ? (
                  <>
                    <span className="wanderplaner-m-nav-distance">{t("mobile.nav.arrived")}</span>
                    <strong>{routeWaypoints.at(-1)?.label || kindLabel("END")}</strong>
                  </>
                ) : nextWaypoint && nextDistance !== null ? (
                  <>
                    <span className="wanderplaner-m-nav-distance">{distance(nextDistance)}</span>
                    <strong>{t("mobile.nav.toWaypoint", { label: nextWaypoint.label || kindLabel(nextWaypoint.kind) })}</strong>
                  </>
                ) : null}
              </span>
            </div>
            <div className="wanderplaner-m-nav-sub">
              <span>{nextWaypoint ? [kindLabel(nextWaypoint.kind), nextEntry?.planned_arrival ? t("mobile.nav.planned", { time: formatHm(nextEntry.planned_arrival) }) : null, nextWaypoint.break_minutes ? t("mobile.table.break", { minutes: String(nextWaypoint.break_minutes) }) : null].filter(Boolean).join(" · ") : t("mobile.nav.privacy")}</span>
              {scheduleDelta !== null && !arrived && (
                <span>{Math.abs(scheduleDelta) < 3 ? t("mobile.nav.onSchedule") : scheduleDelta > 0 ? t("mobile.nav.behindSchedule", { minutes: String(scheduleDelta) }) : t("mobile.nav.aheadOfSchedule", { minutes: String(-scheduleDelta) })}</span>
              )}
            </div>
          </div>
          {navWarning && (
            <div className={`wanderplaner-m-warning wanderplaner-m-warning-${navWarning.tone}`} role="alert">
              <span className="wanderplaner-m-warning-icon" aria-hidden="true">!</span>
              <span className="wanderplaner-m-nav-text">
                <strong>{navWarning.title}</strong>
                <span>{navWarning.text}</span>
              </span>
            </div>
          )}
        </div>
        <div className="wanderplaner-m-nav-side">
          {fix && <span className="wanderplaner-m-gps"><span className="wanderplaner-m-gps-dot" aria-hidden="true" />{t("mobile.nav.accuracy", { value: String(Math.round(fix.accuracy)) })}</span>}
          <button type="button" className={`wanderplaner-m-round${follow ? " wanderplaner-m-round-active" : ""}`} aria-label={t("mobile.nav.recenter")} aria-pressed={follow} onClick={() => { setFollow(true); setFocusPoint(null); }}>
            <MobileIcon name="location" size={18} />
          </button>
        </div>
        <div className="wanderplaner-m-sheet">
          <span className="wanderplaner-m-grabber" aria-hidden="true" />
          {exitOpen && (
            <div className="wanderplaner-m-exit">
              <div className="wanderplaner-m-exit-head">
                <strong>{t("mobile.nav.exit.title")}</strong>
                <button type="button" className="button-icon-soft" aria-label={t("mobile.nav.exit.close")} onClick={() => setExitOpen(false)}>
                  <MobileIcon name="close" size={16} />
                </button>
              </div>
              <span>
                {nearestExit ? (
                  <>
                    {exitDelta !== null
                      ? t(exitDelta >= 0 ? "mobile.nav.exit.ahead" : "mobile.nav.exit.behind", { label: nearestExit.label || kindLabel("EMERGENCY_EXIT"), distance: distance(Math.abs(exitDelta)) })
                      : nearestExit.label || kindLabel("EMERGENCY_EXIT")}
                    {nearestExit.exit_metrics_json ? ` ${t("mobile.nav.exit.then", { distance: distance(nearestExit.exit_metrics_json.distance_m), time: duration(nearestExit.exit_metrics_json.time_to_exit_minutes) })}` : ""}
                    {isUnverified(nearestExit) ? ` ${t("mobile.nav.exit.unverified")}` : ""}
                  </>
                ) : t("mobile.nav.exit.none")}{" "}
                {t("mobile.nav.exit.emergency")}
              </span>
              <div className="wanderplaner-m-exit-actions">
                {nearestExit && (
                  <button type="button" className="button-danger" onClick={() => { setFollow(false); setFocusPoint({ lat: nearestExit.lat, lon: nearestExit.lon }); }}>
                    {t("mobile.nav.exit.show")}
                  </button>
                )}
                <a className="button-secondary" href="tel:1414">{t("mobile.nav.exit.callRega")}</a>
              </div>
            </div>
          )}
          <div className="wanderplaner-m-stats wanderplaner-m-stats-3">
            <div><strong>{alongM !== null ? distance(Math.max(0, totalM - alongM)) : "–"}</strong><span>{t("mobile.nav.remaining")}</span></div>
            <div><strong>{remainingPlanned !== null && fix ? formatClock(nowClock + remainingPlanned) : "–"}</strong><span>{t("mobile.nav.arrival")}</span></div>
            <div><strong>{alongM !== null ? `↑ ${t("units.meters", { value: String(Math.round(remainingAscent(track, alongM))) })}` : "–"}</strong><span>{t("mobile.nav.ascent")}</span></div>
          </div>
          {elevationProfile && (
            <div className="wanderplaner-m-profile-block">
              <HikingTourProfileStrip points={elevationProfile.points} dangerSegments={terrainDanger?.segments} positionM={alongM} compact />
              <div className="wanderplaner-m-legend wanderplaner-m-legend-split">
                <span>{alongM !== null ? t("mobile.nav.walked", { distance: distance(alongM), duration: duration(navStartedAt ? (now - navStartedAt) / 60_000 : 0) }) : ""}</span>
                <span>{alongM !== null ? t("mobile.nav.elevationNow", { value: String(Math.round(elevationAt(track, alongM) ?? fix?.altitude ?? 0)) }) : ""}</span>
              </div>
            </div>
          )}
          <div className="wanderplaner-m-nav-actions">
            <button type="button" className="button-primary" onClick={() => setTracking((value) => !value)}>
              {tracking ? t("mobile.nav.pause") : t("mobile.nav.resume")}
            </button>
            <button type="button" className="button-secondary wanderplaner-m-exit-toggle" aria-pressed={exitOpen} onClick={() => setExitOpen((value) => !value)}>
              {t("mobile.nav.emergencyExit")}
            </button>
            <button type="button" className="button-ghost" onClick={endNavigation}>{t("mobile.nav.end")}</button>
          </div>
        </div>
      </div>
    );
  }

  // Übersicht
  return (
    <div className="wanderplaner-m-screen">
      {mapBlock ?? <div className="wanderplaner-m-map-empty" />}
      <div className="wanderplaner-m-overlay-top">
        <button type="button" className="wanderplaner-m-round" aria-label={t("mobile.backToList")} onClick={() => router.push("/hiking-planner")}>
          <MobileIcon name="chevronLeft" size={20} strokeWidth={2.2} />
        </button>
      </div>
      <div className="wanderplaner-m-sheet wanderplaner-m-sheet-overview">
        <span className="wanderplaner-m-grabber" aria-hidden="true" />
        <div className="wanderplaner-m-title-block">
          <div className="wanderplaner-m-title-meta">
            <Badge variant={STATUS_VARIANT[tour.status] ?? "neutral"}>{STATUS_VARIANT[tour.status] ? t(`status.${tour.status}`) : tour.status}</Badge>
            {metaParts.length > 0 && <span className="wanderplaner-m-muted">{metaParts.join(" · ")}</span>}
          </div>
          <h1 className="wanderplaner-m-title">{tour.title}</h1>
        </div>
        {!hasRoute ? (
          <MobileEmpty title={t("mobile.noRoute.title")} hint={t("mobile.noRoute.hint")} />
        ) : (
          <>
            <div className="wanderplaner-m-stats">
              <div><strong>{tour.route_distance_m != null ? distance(tour.route_distance_m) : "–"}</strong><span>{t("mobile.stats.distance")}</span></div>
              <div><strong>{marchTable ? marchTable.summary.total_lkm.toFixed(1) : "–"}</strong><span>{t("mobile.stats.lkm")}</span></div>
              <div><strong>{marchTable ? duration(marchTable.summary.total_duration_minutes) : "–"}</strong><span>{t("mobile.stats.duration")}</span></div>
              <div><strong>↑ {Math.round(tour.route_ascent_m ?? 0)}</strong><span>{t("mobile.stats.descent", { value: String(Math.round(tour.route_descent_m ?? 0)) })}</span></div>
            </div>
            {elevationProfile && (
              <div className="wanderplaner-m-profile-block">
                <HikingTourProfileStrip points={elevationProfile.points} dangerSegments={terrainDanger?.segments} />
                {profileLegend}
              </div>
            )}
            {canWrite && (
              <div className="wanderplaner-m-section">
                <span className="mobile-eyebrow">{t("detail.route.routingProfile")}</span>
                {recalculating ? (
                  <span className="wanderplaner-m-muted" role="status">{t("detail.route.savingAndCalculating")}</span>
                ) : (
                  <MobileSegmented
                    compact
                    ariaLabel={t("detail.route.routingProfile")}
                    value={tour.routing_profile ?? "wanderwege_bevorzugen"}
                    onChange={(value) => void handleRoutingProfile(value)}
                    options={ROUTING_PROFILES.map((value) => ({ value, label: t(`mobile.routingProfileShort.${value}`) }))}
                  />
                )}
              </div>
            )}
            <div className="wanderplaner-m-actions">
              <button type="button" className="wanderplaner-m-action" onClick={() => openView("table")}>
                <MobileIcon name="todos" size={18} />{t("mobile.actions.marchTable")}
              </button>
              <button type="button" className="wanderplaner-m-action" onClick={() => openView("reko")}>
                <MobileIcon name="check" size={18} />{t("mobile.actions.reconnaissance")}
              </button>
              {/* Druck verlangt hiking.manage (POST /print), wie am Desktop nur mit Schreibrecht. */}
              {canWrite && (
                <button type="button" className="wanderplaner-m-action" onClick={() => setShowPrint(true)}>
                  <MobileIcon name="document" size={18} />{t("mobile.actions.print")}
                </button>
              )}
              <a className="wanderplaner-m-action" href={`/api/hiking-tours/${tour.id}/gpx`}>
                <MobileIcon name="chevronDown" size={18} />{t("mobile.actions.gpx")}
              </a>
            </div>
            <button type="button" className="button-primary wanderplaner-m-wide wanderplaner-m-start" onClick={startNavigation}>
              <MobileIcon name="location" size={18} />{t("mobile.startNavigation")}
            </button>
          </>
        )}
      </div>
      <HikingTourPrintModal tourId={tour.id} open={showPrint} onClose={() => setShowPrint(false)} sheet />
    </div>
  );
}
