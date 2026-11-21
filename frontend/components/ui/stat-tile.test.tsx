import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Sparkline } from "@/components/ui/sparkline";
import { StatTile } from "@/components/ui/stat-tile";

describe("StatTile", () => {
  it("zeigt Wert, Vergleich und ist mit href ein Link", () => {
    render(<StatTile label="Mandanten" value="42" href="/admin/tenants" delta={{ text: "+4 % zum Vormonat", direction: "up", tone: "good" }} />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/admin/tenants");
    expect(link).toHaveTextContent("Mandanten");
    expect(link).toHaveTextContent("42");
    expect(screen.getByText(/\+4 % zum Vormonat/)).toHaveClass("stat-tile-delta-good");
  });

  it("zeigt bei unavailable keinen Wert und keinen Link", () => {
    render(<StatTile label="Fehler (24 h)" value="7" href="/admin/error-logs" unavailable="Keine Berechtigung" delta={{ text: "x", direction: "up", tone: "bad" }} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Keine Berechtigung")).toBeInTheDocument();
    expect(screen.queryByText("7")).toBeNull();
  });

  it("Status als Badge mit Text (nicht nur Farbe)", () => {
    render(<StatTile label="Zustand" value="Warnung" status="warning" statusLabel="2 Warnungen" />);
    expect(screen.getByText("2 Warnungen")).toHaveClass("badge-warning");
  });
});

describe("Sparkline", () => {
  it("ist ein beschriftetes Bild mit einer Linie", () => {
    const { container } = render(<Sparkline values={[1, 3, 2]} label="Verlauf 24 h" tone="danger" />);
    expect(screen.getByRole("img", { name: "Verlauf 24 h" })).toHaveClass("sparkline-danger");
    expect(container.querySelector("polyline")?.getAttribute("points")?.split(" ")).toHaveLength(3);
  });

  it("rendert ohne Werte nichts", () => {
    const { container } = render(<Sparkline values={[]} label="leer" />);
    expect(container.firstChild).toBeNull();
  });
});
