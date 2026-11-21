import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SearchableSelect } from "./searchable-select";

type Tenant = { id: string; name: string };

describe("SearchableSelect.loadOptions (Remote-Modus, Plan §5.1)", () => {
  it("lädt beim Öffnen und nach der Eingabe, filtert nicht selbst, Tastaturauswahl wie lokal", async () => {
    const loadOptions = vi.fn(async (query: string) =>
      query ? [{ id: "t2", name: `Treffer ${query}` }] : [{ id: "t1", name: "Erster" }, { id: "t2", name: "Zweiter" }],
    );
    const onChange = vi.fn();
    render(
      <SearchableSelect<Tenant, string> options={[]} loadOptions={loadOptions} getId={(t) => t.id} getLabel={(t) => t.name} value={null} onChange={onChange} placeholder="Mandant" />,
    );
    fireEvent.keyDown(screen.getByRole("button", { name: "Mandant" }), { key: "ArrowDown" });
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));
    expect(loadOptions).toHaveBeenLastCalledWith("", expect.any(AbortSignal));
    const combo = screen.getByRole("combobox");
    fireEvent.change(combo, { target: { value: "abc" } });
    // Serverergebnis wird nicht erneut nach dem Begriff gefiltert
    await waitFor(() => expect(screen.getByRole("option", { name: "Treffer abc" })).toBeInTheDocument());
    expect(loadOptions).toHaveBeenLastCalledWith("abc", expect.any(AbortSignal));
    fireEvent.keyDown(combo, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith({ id: "t2", name: "Treffer abc" });
  });

  it("zeigt die gewählte Option aus selectedOption, auch ohne Treffer", () => {
    render(
      <SearchableSelect<Tenant, string>
        options={[]}
        loadOptions={async () => []}
        selectedOption={{ id: "t9", name: "Verein Neun" }}
        getId={(t) => t.id}
        getLabel={(t) => t.name}
        value="t9"
        onChange={() => undefined}
      />,
    );
    expect(screen.getByRole("button", { name: "Verein Neun" })).toBeInTheDocument();
  });
});
