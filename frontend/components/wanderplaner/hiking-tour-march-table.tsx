"use client";

import { useTranslations } from "next-intl";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { PillMenu } from "@/components/ui/pill-menu";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { HikingTourWaypoint, HikingTourWaypointVerificationStatus, HikingTourWaypointKind, MarchTimeEntry, MarchTimeTable, TerrainDangerSegment } from "@/types/api";

type TFunc = (key: string, values?: Record<string, string | number>) => string;

export function formatHm(time: string | null): string {
  return time ? time.slice(0, 5) : "–";
}

export function formatMinutes(t: TFunc, minutes: number): string {
  const rounded = Math.round(minutes);
  const hours = Math.floor(rounded / 60);
  const rest = rounded % 60;
  return hours > 0 ? t("units.hoursMinutes", { hours, minutes: rest }) : t("units.minutes", { minutes: rest });
}

// Auftrag Abschnitt 11: Verifizierungsstatus automatisch erkannter sicherheitsrelevanter
// Punkte (Entscheidungspunkte, Notausstiege) - nie als geprüfte Tatsache dargestellt.
const VERIFICATION_VARIANT: Record<HikingTourWaypointVerificationStatus, BadgeVariant> = {
  AUTO_DETECTED: "info",
  NEEDS_VERIFICATION: "warning",
  VERIFIED: "success",
  REJECTED: "danger",
};

const VERIFICATION_STATUSES = Object.keys(VERIFICATION_VARIANT) as HikingTourWaypointVerificationStatus[];

// Gefahreneinschätzung (Auftrag): nur die beiden "echten" Gefahrenstufen bekommen hier ein
// Badge - "normal" ist der unauffällige Regelfall und braucht keine eigene Markierung.
export type RowDanger = "steep_exposed" | "alpine";

const DANGER_VARIANT: Record<RowDanger, BadgeVariant> = {
  steep_exposed: "warning",
  alpine: "info",
};

/** Abschnitt dieser Zeile (vom vorherigen bis zu diesem Wegpunkt) gegen die Gefahrensegmente
 * prüfen - "alpine" hat Vorrang, falls beide in diesem Abschnitt vorkommen (gleiche Priorität
 * wie app/core/route_danger.py::merge_with_official_status). */
export function rowDanger(entry: MarchTimeEntry | undefined, segments: TerrainDangerSegment[] | undefined): RowDanger | null {
  if (!entry || !segments?.length) return null;
  const from = entry.cumulative_distance_m - entry.segment_distance_m;
  const to = entry.cumulative_distance_m;
  const overlapping = segments.filter((segment) => segment.danger !== "normal" && segment.from_m < to && segment.to_m > from);
  if (overlapping.some((segment) => segment.danger === "alpine")) return "alpine";
  if (overlapping.some((segment) => segment.danger === "steep_exposed")) return "steep_exposed";
  return null;
}

/** Sequenz des Kontrollpunkts auf der Route, an dem ein Notausstieg abzweigt. Alte Analysen
 * kodieren sie im reservierten Bereich ab 500000. */
export function exitSourceSequence(waypoint: HikingTourWaypoint): number {
  return waypoint.exit_metrics_json?.source_sequence ?? (waypoint.sequence >= 500000 ? waypoint.sequence - 500000 : waypoint.sequence);
}

/** Notausstiege stehen direkt nach dem zugehörigen Kontrollpunkt. */
export function orderWaypoints(waypoints: HikingTourWaypoint[]): HikingTourWaypoint[] {
  const position = (waypoint: HikingTourWaypoint) => waypoint.kind === "EMERGENCY_EXIT" ? exitSourceSequence(waypoint) + 0.5 : waypoint.sequence;
  return [...waypoints].sort((a, b) => position(a) - position(b));
}

type Props = {
  table: MarchTimeTable | null;
  waypoints: HikingTourWaypoint[];
  canWrite?: boolean;
  dangerSegments?: TerrainDangerSegment[];
  onUpdateBreakMinutes?: (waypoint: HikingTourWaypoint, minutes: number) => void;
  onVerificationChange?: (waypoint: HikingTourWaypoint, status: HikingTourWaypointVerificationStatus) => void;
  onDeleteWaypoint?: (waypoint: HikingTourWaypoint) => void;
};

export function HikingTourMarchTable({ table, waypoints, canWrite = false, dangerSegments, onUpdateBreakMinutes, onVerificationChange, onDeleteWaypoint }: Props) {
  const t = useTranslations("wanderplaner");
  const kindLabel = (kind: HikingTourWaypointKind) => t(`kind.${kind}`);
  const verificationLabel = (status: HikingTourWaypointVerificationStatus) => t(`verification.${status}`);
  const verificationOptions = VERIFICATION_STATUSES.map((value) => ({
    value,
    label: verificationLabel(value),
    variant: VERIFICATION_VARIANT[value],
  }));
  const duration = (value: number) => formatMinutes(t, value);
  const km = (meters: number, digits: number) => t("units.km", { value: (meters / 1000).toFixed(digits) });
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>;
  const entries = new Map(table?.entries.map((entry) => [entry.sequence, entry]) ?? []);
  const orderedWaypoints = orderWaypoints(waypoints);
  const dash = <span className="muted">–</span>;
  return (
    <div className="wanderplaner-march-table">
      <DataToolbar title={t("marchTable.title")} description={table
        ? t("marchTable.speedFactor", { value: String(table.speed_factor_kmh) })
        : t("marchTable.noRoute")} />
      <DataTable
        columns={[
          t("marchTable.columns.index"), t("marchTable.columns.name"), t("marchTable.columns.type"),
          t("marchTable.columns.elevation"), t("marchTable.columns.distance"), t("marchTable.columns.cumulativeDistance"),
          t("marchTable.columns.ascent"), t("marchTable.columns.descent"), t("marchTable.columns.lkm"),
          t("marchTable.columns.time"), t("marchTable.columns.cumulativeTime"), t("marchTable.columns.arrival"),
          t("marchTable.columns.break"), t("marchTable.columns.departure"), t("marchTable.columns.remarks"),
          t("marchTable.columns.status"), t("marchTable.columns.actions"),
        ]}
        emptyMessage={t("marchTable.empty")}
      >
        {orderedWaypoints.map((waypoint, index) => {
          const candidate = entries.get(waypoint.sequence);
          const entry = candidate?.kind === waypoint.kind ? candidate : undefined;
          const elevation = entry?.elevation_m ?? waypoint.elevation_m;
          const metrics = waypoint.decision_metrics_json;
          const verificationStatus = waypoint.verification_status ?? (waypoint.auto_generated ? "AUTO_DETECTED" : null);
          const danger = rowDanger(entry, dangerSegments);
          return (
            <tr key={waypoint.id}>
              <td>{index + 1}</td>
              <td>
                {waypoint.label || dash}
                <div className="field-help">{waypoint.lat.toFixed(4)}, {waypoint.lon.toFixed(4)}</div>
              </td>
              <td>{kindLabel(waypoint.kind)}</td>
              <td>{elevation != null ? t("units.meters", { value: String(Math.round(elevation)) }) : dash}</td>
              <td>{entry ? km(entry.segment_distance_m, 2) : dash}</td>
              <td>{entry ? km(entry.cumulative_distance_m, 2) : dash}</td>
              <td>{entry ? t("units.meters", { value: String(Math.round(entry.segment_ascent_m)) }) : dash}</td>
              <td>{entry ? t("units.meters", { value: String(Math.round(entry.segment_descent_m)) }) : dash}</td>
              <td>{entry ? entry.segment_lkm.toFixed(2) : dash}</td>
              <td>{entry ? duration(entry.segment_duration_minutes) : dash}</td>
              <td>{entry ? duration(entry.cumulative_duration_minutes) : dash}</td>
              <td>{formatHm(entry?.planned_arrival ?? null)}</td>
              <td>{canWrite && onUpdateBreakMinutes ? (
                <input key={`${waypoint.id}-${waypoint.break_minutes ?? 0}`} type="number" min={0}
                  defaultValue={waypoint.break_minutes ?? 0} aria-label={t("marchTable.breakMinutesAria")}
                  className="wanderplaner-break-input" onBlur={(event) => {
                    const minutes = Number(event.target.value) || 0;
                    if (minutes !== (waypoint.break_minutes ?? 0)) onUpdateBreakMinutes(waypoint, minutes);
                  }} />
              ) : waypoint.break_minutes ? t("units.minutes", { minutes: String(waypoint.break_minutes) }) : dash}</td>
              <td>{formatHm(entry?.planned_departure ?? null)}</td>
              <td>
                {waypoint.description || entry?.remarks || dash}
                {waypoint.description && entry?.remarks && entry.remarks !== waypoint.description && <div className="field-help">{entry.remarks}</div>}
                {metrics && <div className="field-help">
                  {t("marchTable.decisionMetrics", {
                    fromStart: duration(metrics.time_from_start_minutes),
                    toEnd: duration(metrics.time_to_end_minutes),
                    back: duration(metrics.time_back_minutes),
                  })}
                  {metrics.nearest_exit_label && metrics.time_to_exit_minutes !== null && t("marchTable.nearestExit", { time: duration(metrics.time_to_exit_minutes) })}
                </div>}
              </td>
              <td>{verificationStatus || danger ? (
                <div className="wanderplaner-row-badges">
                  {danger && <Badge variant={DANGER_VARIANT[danger]}>{t(`danger.badge.${danger}`)}</Badge>}
                  {verificationStatus && (canWrite && onVerificationChange ? (
                    <PillMenu value={verificationStatus} options={verificationOptions}
                      onChange={(status) => onVerificationChange(waypoint, status)} />
                  ) : <Badge variant={VERIFICATION_VARIANT[verificationStatus]}>{verificationLabel(verificationStatus)}</Badge>)}
                </div>
              ) : dash}</td>
              <td>
                <div className="wanderplaner-row-actions">
                {canWrite && onDeleteWaypoint && (waypoint.kind === "USER_DEFINED" || waypoint.auto_generated) && (
                  <button type="button" className="button-secondary button-ghost" onClick={() => onDeleteWaypoint(waypoint)}>{t("actions.remove")}</button>
                )}
                </div>
              </td>
            </tr>
          );
        })}
      </DataTable>
      {table && <div className="wanderplaner-route-summary">
        <span>{t.rich("marchTable.summary.totalDistance", { value: km(table.summary.total_distance_m, 1), strong })}</span>
        <span>
          {t.rich("marchTable.summary.ascentDescent", {
            ascent: String(Math.round(table.summary.total_ascent_m)),
            descent: String(Math.round(table.summary.total_descent_m)),
            strong,
          })}
        </span>
        <span>{t.rich("marchTable.summary.lkm", { value: t("units.lkm", { value: table.summary.total_lkm.toFixed(1) }), strong })}</span>
        <span>{t.rich("marchTable.summary.walkingTime", { value: duration(table.summary.walking_duration_minutes), strong })}</span>
        <span>{t.rich("marchTable.summary.breaks", { value: duration(table.summary.break_duration_minutes), strong })}</span>
        <span>{t.rich("marchTable.summary.totalTime", { value: duration(table.summary.total_duration_minutes), strong })}</span>
      </div>}
    </div>
  );
}
