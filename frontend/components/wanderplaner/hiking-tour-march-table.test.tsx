import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { HikingTourWaypoint, MarchTimeTable } from "@/types/api";

import { HikingTourMarchTable } from "./hiking-tour-march-table";

function table(overrides: Partial<MarchTimeTable> = {}): MarchTimeTable {
  return {
    speed_factor_kmh: 4,
    entries: [
      {
        sequence: 1,
        label: "Start",
        kind: "START",
        elevation_m: 500,
        segment_distance_m: 0,
        cumulative_distance_m: 0,
        segment_ascent_m: 0,
        segment_descent_m: 0,
        segment_lkm: 0,
        cumulative_lkm: 0,
        segment_duration_minutes: 0,
        cumulative_duration_minutes: 0,
        planned_arrival: "08:00:00",
        break_minutes: 0,
        planned_departure: "08:00:00",
        remarks: null,
      },
      {
        sequence: 2,
        label: "Ziel",
        kind: "END",
        elevation_m: 1400,
        segment_distance_m: 5000,
        cumulative_distance_m: 5000,
        segment_ascent_m: 900,
        segment_descent_m: 0,
        segment_lkm: 14,
        cumulative_lkm: 14,
        segment_duration_minutes: 210,
        cumulative_duration_minutes: 210,
        planned_arrival: "11:30:00",
        break_minutes: 15,
        planned_departure: "11:45:00",
        remarks: "Gipfelrast",
      },
    ],
    summary: {
      total_distance_m: 5000,
      total_ascent_m: 900,
      total_descent_m: 0,
      total_lkm: 14,
      walking_duration_minutes: 210,
      break_duration_minutes: 15,
      total_duration_minutes: 225,
    },
    ...overrides,
  };
}

function waypoints(): HikingTourWaypoint[] {
  return table().entries.map((entry) => ({
    id: String(entry.sequence), sequence: entry.sequence, kind: entry.kind,
    label: entry.label, description: null, lat: 47, lon: 8,
    elevation_m: entry.elevation_m, break_minutes: entry.break_minutes,
    break_reason: null, auto_generated: false, verification_status: null,
    decision_metrics_json: null, exit_metrics_json: null, created_at: "", updated_at: "",
  }));
}

describe("HikingTourMarchTable", () => {
  it("renders one row per waypoint with formatted times and the Lkm-based summary", () => {
    render(<HikingTourMarchTable table={table()} waypoints={waypoints()} />);

    expect(screen.getAllByText("08:00")).toHaveLength(2); // Ankunft und Abmarsch am Start sind identisch
    expect(screen.getByText("11:30")).toBeInTheDocument();
    expect(screen.getByText("11:45")).toBeInTheDocument();
    expect(screen.getByText("Gipfelrast")).toBeInTheDocument();
    expect(screen.getAllByText("3h 30min").length).toBeGreaterThan(0); // 210 Minuten Gehzeit

    expect(screen.getByText("14.0 Lkm")).toBeInTheDocument();
    expect(screen.getByText("5.0 km")).toBeInTheDocument();
  });

  it("shows a dash instead of '0 min' in the Pause column for waypoints without a break", () => {
    render(<HikingTourMarchTable table={table()} waypoints={waypoints()} />);

    const startRow = screen.getByText("Start").closest("tr")!;
    const pauseCell = startRow.querySelectorAll("td")[11];
    expect(pauseCell.textContent).toBe("–");

    const endRow = screen.getByText("Ziel").closest("tr")!;
    expect(endRow.querySelectorAll("td")[11].textContent).toBe("15 min");
  });
});

it("keeps waypoints editable in a single table before route calculation", () => {
  const onUpdateBreakMinutes = vi.fn();
  const onDeleteWaypoint = vi.fn();
  const point = { ...waypoints()[0], kind: "USER_DEFINED" as const, label: "Zwischenhalt" };
  render(<HikingTourMarchTable table={null} waypoints={[point]} canWrite
    onUpdateBreakMinutes={onUpdateBreakMinutes} onDeleteWaypoint={onDeleteWaypoint} />);
  expect(screen.getAllByRole("table")).toHaveLength(1);
  const row = screen.getByText("Zwischenhalt").closest("tr")!;
  expect(row.querySelectorAll("td")[3].textContent).toBe("–");
  fireEvent.blur(screen.getByRole("spinbutton"), { target: { value: "10" } });
  expect(onUpdateBreakMinutes).toHaveBeenCalledWith(point, 10);
  fireEvent.click(screen.getByRole("button", { name: "Entfernen" }));
  expect(onDeleteWaypoint).toHaveBeenCalledWith(point);
});

it("retains emergency exits without inventing marching times", () => {
  const exit = { ...waypoints()[0], id: "exit", sequence: 3, kind: "EMERGENCY_EXIT" as const,
    label: "Ausstieg", verification_status: "NEEDS_VERIFICATION" as const };
  render(<HikingTourMarchTable table={table()} waypoints={[...waypoints(), exit]} />);
  const row = screen.getByText("Ausstieg").closest("tr")!;
  expect(row.querySelectorAll("td")[8].textContent).toBe("–");
  expect(screen.getByText("Vor Ort prüfen")).toBeInTheDocument();
  expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Entfernen" })).not.toBeInTheDocument();
});

it("offers all review actions for automatic points without an initial status", () => {
  const onVerificationChange = vi.fn();
  const point = { ...waypoints()[0], auto_generated: true, verification_status: null };
  render(<HikingTourMarchTable table={null} waypoints={[point]} canWrite onVerificationChange={onVerificationChange} />);
  for (const [label, status] of [["Vom Leiter bestätigt", "VERIFIED"], ["Vor Ort prüfen", "NEEDS_VERIFICATION"], ["Verworfen", "REJECTED"]]) {
    fireEvent.click(screen.getByRole("button", { name: "Automatisch erkannt" }));
    fireEvent.click(screen.getByText(label));
    expect(onVerificationChange).toHaveBeenLastCalledWith(point, status);
  }
});
