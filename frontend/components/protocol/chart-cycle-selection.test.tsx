import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChartCycleSelection } from "./chart-cycle-selection";

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: vi.fn().mockResolvedValue([{ id: "cycle-1", name: "Scharjahr" }]),
}));

describe("Zykluswahl für Diagramme", () => {
  it("zeigt gespeicherte relative Auswahl und übernimmt den vorherigen Zyklus", async () => {
    const onChange = vi.fn();
    render(<ChartCycleSelection config={{ cycle_config_id: "cycle-1", cycle_offset: -2 }} onChange={onChange} />);
    await waitFor(() => expect(screen.getByText("Scharjahr")).toBeTruthy());
    const selected = screen.getAllByRole("button").filter((button) => button.getAttribute("aria-pressed") === "true");
    expect(selected).toHaveLength(1);
    expect(selected[0].textContent).toContain("2");
    fireEvent.click(screen.getByRole("button", { name: /Vorheriger Zyklus/ }));
    expect(onChange).toHaveBeenCalledWith({ cycle_config_id: "cycle-1", cycle_offset: -1 });
  });

  it("zeigt ohne Zyklusfilter keine relative Auswahl", () => {
    render(<ChartCycleSelection config={{}} onChange={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Aktueller Zyklus" })).toBeNull();
  });
});
