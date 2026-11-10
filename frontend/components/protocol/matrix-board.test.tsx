import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MatrixBoardHeader, MatrixEmptyValue, MatrixPeopleChips, MatrixTableView } from "./matrix-board";

describe("MatrixBoard", () => {
  it("shows the column source and switches the view", () => {
    const onViewChange = vi.fn();
    render(<MatrixBoardHeader source="Spalten aus «Gruppen»" view="cards" onViewChange={onViewChange} />);
    expect(screen.getByText("Spalten aus «Gruppen»")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Karten" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Tabelle" }));
    expect(onViewChange).toHaveBeenCalledWith("table");
  });

  it("renders people as chips with initials and an add button", () => {
    const onAdd = vi.fn();
    render(<MatrixPeopleChips names={["Anna Berger", "Luca"]} onEdit={vi.fn()} onAdd={onAdd} />);
    expect(screen.getByRole("button", { name: /Anna Berger/ })).toHaveTextContent("AB");
    fireEvent.click(screen.getByRole("button", { name: "Person hinzufügen" }));
    expect(onAdd).toHaveBeenCalled();
  });

  it("offers adding in empty editable cells and a dash otherwise", () => {
    const onAdd = vi.fn();
    const { rerender } = render(<MatrixEmptyValue addLabel="Person" onAdd={onAdd} />);
    fireEvent.click(screen.getByRole("button", { name: "+ Person" }));
    expect(onAdd).toHaveBeenCalled();
    rerender(<MatrixEmptyValue />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("summarises every cell in the table view", () => {
    render(
      <MatrixTableView
        columns={[{ id: "a", name: "Wölfe", colorIndex: 0 }, { id: "b", name: "Füchse", colorIndex: 1 }]}
        rows={[{ id: "r1", label: "Leiter", locked: true, cells: ["Anna Berger", ""] }]}
      />
    );
    expect(screen.getByRole("columnheader", { name: "Wölfe" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: /Leiter/ })).toHaveTextContent("gesperrt");
    expect(screen.getByRole("cell", { name: "Anna Berger" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "—" })).toBeInTheDocument();
  });
});
