import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { locales } from "@/i18n/locale-config.generated";
import { FEATURES } from "@/lib/features.generated";
import type { PublicFeature, PublicPlan } from "@/types/api";

import { WebsitePlanComparison } from "./website-plan-comparison";

function plan(code: string, overrides: Partial<PublicPlan> = {}): PublicPlan {
  return { code, name: code, description: null, price_monthly_rp: 1900, price_yearly_rp: 19000, included_user_limit: 10, included_storage_bytes: 5 * 1024 ** 3, is_featured: false, features: [], ...overrides };
}

const features: PublicFeature[] = [
  { code: "task_packages", name: "Aufgabenpakete", description: "Wiederkehrende Aufgaben", module: "meetings", standalone_price_monthly_rp: null },
  { code: "finance", name: "Finanzen", description: null, module: "finance", standalone_price_monthly_rp: 500 },
];

describe("WebsitePlanComparison", () => {
  it("shows prices, limits and every feature per plan from the catalog data", () => {
    render(
      <WebsitePlanComparison
        plans={[
          plan("Basis", { features: [{ code: "task_packages", name: "Aufgabenpakete" }] }),
          plan("Verein", { is_featured: true, price_yearly_rp: null, included_user_limit: null, included_storage_bytes: null, features: [{ code: "task_packages", name: "Aufgabenpakete" }, { code: "finance", name: "Finanzen" }] }),
        ]}
        features={features}
      />
    );
    const table = screen.getByRole("table", { name: "Funktionen und Abos im Vergleich" });
    expect(within(table.querySelector("thead") as HTMLElement).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(["Funktion", "Basis", "Beliebteste WahlVerein"]);
    const row = (name: string | RegExp) => within(table).getByRole("rowheader", { name }).closest("tr") as HTMLElement;
    expect(within(row("Preis pro Monat")).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["CHF 19.–", "CHF 19.–"]);
    expect(within(row("Preis pro Jahr")).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["CHF 190.–", "Auf Anfrage"]);
    expect(within(row("Benutzer")).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["Bis 10", "Unbegrenzt"]);
    expect(within(row("Speicher")).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["5 GB", "Unbegrenzt"]);
    // Gruppen nach Produktmodul, Beschreibung aus dem Katalog
    expect(within(table).getByRole("columnheader", { name: "Sitzungen und Protokolle" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Finanzen" })).toBeInTheDocument();
    expect(within(row(/Aufgabenpakete/)).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["✓Enthalten", "✓Enthalten"]);
    expect(within(row(/^Finanzen/)).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["ZubuchbarCHF 5.– / Monat", "✓Enthalten"]);
    expect(within(table).getByText("Wiederkehrende Aufgaben")).toBeInTheDocument();
  });

  it("renders nothing without bookable plans", () => {
    const { container } = render(<WebsitePlanComparison plans={[]} features={features} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("has a heading for every product module in every language", async () => {
    const modules = new Set([...FEATURES.map((feature) => feature.module), "other"]);
    for (const locale of locales) {
      const messages = (await import(`@/messages/${locale}/website.json`)).default as { comparison: { module: Record<string, string> } };
      for (const module of modules) expect(messages.comparison.module[module], `${locale}: ${module}`).toBeTruthy();
    }
  });
});
