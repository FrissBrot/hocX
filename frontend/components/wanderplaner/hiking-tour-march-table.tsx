"use client";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { HikingTourWaypointKind, MarchTimeTable } from "@/types/api";

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

function formatHm(time: string | null): string {
  return time ? time.slice(0, 5) : "–";
}

function formatMinutes(minutes: number): string {
  const rounded = Math.round(minutes);
  const hours = Math.floor(rounded / 60);
  const rest = rounded % 60;
  return hours > 0 ? `${hours}h ${rest}min` : `${rest} min`;
}

export function HikingTourMarchTable({ table }: { table: MarchTimeTable }) {
  return (
    <div>
      <DataToolbar title="Marschzeittabelle" description={`Geschwindigkeitsfaktor: ${table.speed_factor_kmh} Lkm/h`} />
      <DataTable
        columns={["#", "Wegpunkt", "Höhe", "Distanz", "Kum. Distanz", "Auf", "Ab", "Lkm", "Zeit", "Kum. Zeit", "Ankunft", "Pause", "Abmarsch", "Bemerkungen"]}
        emptyMessage="Keine Marschzeittabelle verfügbar."
      >
        {table.entries.map((entry) => (
          <tr key={entry.sequence}>
            <td>{entry.sequence}</td>
            <td>{entry.label || KIND_LABEL[entry.kind]}</td>
            <td>{entry.elevation_m !== null ? `${Math.round(entry.elevation_m)} m` : <span className="muted">–</span>}</td>
            <td>{(entry.segment_distance_m / 1000).toFixed(2)} km</td>
            <td>{(entry.cumulative_distance_m / 1000).toFixed(2)} km</td>
            <td>{Math.round(entry.segment_ascent_m)} m</td>
            <td>{Math.round(entry.segment_descent_m)} m</td>
            <td>{entry.segment_lkm.toFixed(2)}</td>
            <td>{formatMinutes(entry.segment_duration_minutes)}</td>
            <td>{formatMinutes(entry.cumulative_duration_minutes)}</td>
            <td>{formatHm(entry.planned_arrival)}</td>
            <td>{entry.break_minutes > 0 ? `${entry.break_minutes} min` : <span className="muted">–</span>}</td>
            <td>{formatHm(entry.planned_departure)}</td>
            <td>{entry.remarks || <span className="muted">–</span>}</td>
          </tr>
        ))}
      </DataTable>
      <div className="wanderplaner-route-summary">
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
      </div>
    </div>
  );
}
