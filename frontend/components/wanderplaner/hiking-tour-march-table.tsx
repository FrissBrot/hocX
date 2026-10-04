"use client";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { PillMenu } from "@/components/ui/pill-menu";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { HikingTourWaypoint, HikingTourWaypointVerificationStatus, HikingTourWaypointKind, MarchTimeEntry, MarchTimeTable, TerrainDangerSegment } from "@/types/api";

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

function formatHm(time: string | null): string {
  return time ? time.slice(0, 5) : "–";
}

function formatMinutes(minutes: number): string {
  const rounded = Math.round(minutes);
  const hours = Math.floor(rounded / 60);
  const rest = rounded % 60;
  return hours > 0 ? `${hours}h ${rest}min` : `${rest} min`;
}

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

// Gefahreneinschätzung (Auftrag): nur die beiden "echten" Gefahrenstufen bekommen hier ein
// Badge - "normal" ist der unauffällige Regelfall und braucht keine eigene Markierung.
type RowDanger = "steep_exposed" | "alpine";

const DANGER_LABEL: Record<RowDanger, string> = {
  steep_exposed: "Steil/ausgesetzt",
  alpine: "Alpin",
};

const DANGER_VARIANT: Record<RowDanger, BadgeVariant> = {
  steep_exposed: "warning",
  alpine: "info",
};

/** Abschnitt dieser Zeile (vom vorherigen bis zu diesem Wegpunkt) gegen die Gefahrensegmente
 * prüfen - "alpine" hat Vorrang, falls beide in diesem Abschnitt vorkommen (gleiche Priorität
 * wie app/core/route_danger.py::merge_with_official_status). */
function rowDanger(entry: MarchTimeEntry | undefined, segments: TerrainDangerSegment[] | undefined): RowDanger | null {
  if (!entry || !segments?.length) return null;
  const from = entry.cumulative_distance_m - entry.segment_distance_m;
  const to = entry.cumulative_distance_m;
  const overlapping = segments.filter((segment) => segment.danger !== "normal" && segment.from_m < to && segment.to_m > from);
  if (overlapping.some((segment) => segment.danger === "alpine")) return "alpine";
  if (overlapping.some((segment) => segment.danger === "steep_exposed")) return "steep_exposed";
  return null;
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
  const entries = new Map(table?.entries.map((entry) => [entry.sequence, entry]) ?? []);
  // Notausstiege stehen direkt nach dem zugehörigen Kontrollpunkt. Alte Analysen
  // kodieren dessen Sequenz im reservierten Bereich ab 500000.
  const position = (waypoint: HikingTourWaypoint) => waypoint.kind === "EMERGENCY_EXIT"
    ? (waypoint.exit_metrics_json?.source_sequence ?? (waypoint.sequence >= 500000 ? waypoint.sequence - 500000 : waypoint.sequence)) + 0.5
    : waypoint.sequence;
  const orderedWaypoints = [...waypoints].sort((a, b) => position(a) - position(b));
  const dash = <span className="muted">–</span>;
  return (
    <div className="wanderplaner-march-table">
      <DataToolbar title="Wegpunkte & Marschtabelle" description={table
        ? `Geschwindigkeitsfaktor: ${table.speed_factor_kmh} Lkm/h`
        : "Route berechnen, um Distanzen und Marschzeiten anzuzeigen."} />
      <DataTable
        columns={["#", "Name", "Typ", "Höhe", "Distanz", "Kum. Distanz", "Auf", "Ab", "Lkm", "Zeit", "Kum. Zeit", "Ankunft", "Pause", "Abmarsch", "Bemerkungen", "Status", "Aktionen"]}
        emptyMessage="Keine Wegpunkte."
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
              <td>{KIND_LABEL[waypoint.kind]}</td>
              <td>{elevation != null ? `${Math.round(elevation)} m` : dash}</td>
              <td>{entry ? `${(entry.segment_distance_m / 1000).toFixed(2)} km` : dash}</td>
              <td>{entry ? `${(entry.cumulative_distance_m / 1000).toFixed(2)} km` : dash}</td>
              <td>{entry ? `${Math.round(entry.segment_ascent_m)} m` : dash}</td>
              <td>{entry ? `${Math.round(entry.segment_descent_m)} m` : dash}</td>
              <td>{entry ? entry.segment_lkm.toFixed(2) : dash}</td>
              <td>{entry ? formatMinutes(entry.segment_duration_minutes) : dash}</td>
              <td>{entry ? formatMinutes(entry.cumulative_duration_minutes) : dash}</td>
              <td>{formatHm(entry?.planned_arrival ?? null)}</td>
              <td>{canWrite && onUpdateBreakMinutes ? (
                <input key={`${waypoint.id}-${waypoint.break_minutes ?? 0}`} type="number" min={0}
                  defaultValue={waypoint.break_minutes ?? 0} aria-label="Pause in Minuten"
                  className="wanderplaner-break-input" onBlur={(event) => {
                    const minutes = Number(event.target.value) || 0;
                    if (minutes !== (waypoint.break_minutes ?? 0)) onUpdateBreakMinutes(waypoint, minutes);
                  }} />
              ) : waypoint.break_minutes ? `${waypoint.break_minutes} min` : dash}</td>
              <td>{formatHm(entry?.planned_departure ?? null)}</td>
              <td>
                {waypoint.description || entry?.remarks || dash}
                {waypoint.description && entry?.remarks && entry.remarks !== waypoint.description && <div className="field-help">{entry.remarks}</div>}
                {metrics && <div className="field-help">
                  Ab Start: {formatMinutes(metrics.time_from_start_minutes)} · Bis Ziel: {formatMinutes(metrics.time_to_end_minutes)} · Zurück: {formatMinutes(metrics.time_back_minutes)}
                  {metrics.nearest_exit_label && metrics.time_to_exit_minutes !== null && <> · Nächster Ausstieg: {formatMinutes(metrics.time_to_exit_minutes)}</>}
                </div>}
              </td>
              <td>{verificationStatus || danger ? (
                <div className="wanderplaner-row-badges">
                  {danger && <Badge variant={DANGER_VARIANT[danger]}>{DANGER_LABEL[danger]}</Badge>}
                  {verificationStatus && (canWrite && onVerificationChange ? (
                    <PillMenu value={verificationStatus} options={VERIFICATION_OPTIONS}
                      onChange={(status) => onVerificationChange(waypoint, status)} />
                  ) : <Badge variant={VERIFICATION_VARIANT[verificationStatus]}>{VERIFICATION_LABEL[verificationStatus]}</Badge>)}
                </div>
              ) : dash}</td>
              <td>
                <div className="wanderplaner-row-actions">
                {canWrite && onDeleteWaypoint && (waypoint.kind === "USER_DEFINED" || waypoint.auto_generated) && (
                  <button type="button" className="button-secondary button-ghost" onClick={() => onDeleteWaypoint(waypoint)}>Entfernen</button>
                )}
                </div>
              </td>
            </tr>
          );
        })}
      </DataTable>
      {table && <div className="wanderplaner-route-summary">
        <span>
          Gesamtdistanz: <strong>{(table.summary.total_distance_m / 1000).toFixed(1)} km</strong>
        </span>
        <span>
          Aufstieg/Abstieg: <strong>{Math.round(table.summary.total_ascent_m)} / {Math.round(table.summary.total_descent_m)} m</strong>
        </span>
        <span>
          Leistungskilometer: <strong>{table.summary.total_lkm.toFixed(1)} Lkm</strong>
        </span>
        <span>
          Marschzeit: <strong>{formatMinutes(table.summary.walking_duration_minutes)}</strong>
        </span>
        <span>
          Pausen: <strong>{formatMinutes(table.summary.break_duration_minutes)}</strong>
        </span>
        <span>
          Gesamtzeit: <strong>{formatMinutes(table.summary.total_duration_minutes)}</strong>
        </span>
      </div>}
    </div>
  );
}
