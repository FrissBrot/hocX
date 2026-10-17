import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ browserApiFetch: vi.fn() }));

import { ChargeFilter, daysUntil, TenantBillingCard, TenantOverdueBanner } from "./tenant-charges";
import type { TenantPortalCharge, TenantPortalCharges } from "@/types/api";

function charge(id: string, status: TenantPortalCharge["status"], start: string, end: string, due: string, paidOn: string | null = null): TenantPortalCharge {
  return { id, period_start: start, period_end: end, billing_cycle: "monthly", amount_rp: 19900, lines: [], status, due_on: due, paid_on: paidOn };
}

const data: TenantPortalCharges = {
  items: [
    charge("c4", "open", "2026-10-01", "2026-11-01", "2099-10-31"),
    charge("c3", "overdue", "2026-09-01", "2026-10-01", "2026-10-01"),
    charge("c2", "waived", "2026-08-01", "2026-09-01", "2026-08-31"),
    charge("c1", "paid", "2026-07-01", "2026-08-01", "2026-07-31", "2026-07-09"),
  ],
  open: { count: 2, amount_rp: 39800 },
  overdue: { count: 1, amount_rp: 19900 },
  payment_term_days: 30,
};

function Card() {
  const [filter, setFilter] = useState<ChargeFilter>("all");
  return <TenantBillingCard charges={data} filter={filter} onFilterChange={setFilter} />;
}

describe("TenantBillingCard", () => {
  it("zeigt alle vier Status und filtert offen/erledigt", () => {
    render(<Card />);
    expect(screen.getByRole("heading", { name: "Abrechnungsperioden" })).toBeInTheDocument();
    for (const label of ["Offen", "Überfällig", "Erlassen", "Bezahlt"]) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    expect(screen.getByText("am 09.07.2026")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(4);

    fireEvent.click(screen.getByRole("tab", { name: /Erledigt/ }));
    expect(screen.queryByText("01.10.2026 – 31.10.2026")).not.toBeInTheDocument();
    expect(screen.getByText("01.07.2026 – 31.07.2026")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /^Offen/ }));
    expect(screen.getByText("01.10.2026 – 31.10.2026")).toBeInTheDocument();
    expect(screen.queryByText("01.07.2026 – 31.07.2026")).not.toBeInTheDocument();
  });
});

describe("TenantOverdueBanner", () => {
  it("nennt Betrag und Periode und springt zu den offenen Perioden", () => {
    const onShow = vi.fn();
    render(<TenantOverdueBanner charges={data} onShow={onShow} />);
    expect(screen.getByText("CHF 199.00 überfällig")).toBeInTheDocument();
    expect(screen.getByText(/Periode 01.09.2026 – 30.09.2026 war am 01.10.2026 fällig/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Anzeigen" }));
    expect(onShow).toHaveBeenCalled();
  });

  it("bleibt ohne überfällige Perioden leer", () => {
    const { container } = render(<TenantOverdueBanner charges={{ ...data, items: data.items.filter((c) => c.status !== "overdue") }} onShow={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("daysUntil", () => {
  it("zählt ganze Kalendertage", () => {
    const today = new Date(2026, 9, 17, 23, 30);
    expect(daysUntil("2026-10-31", today)).toBe(14);
    expect(daysUntil("2026-10-01", today)).toBe(-16);
    expect(daysUntil("2026-10-17", today)).toBe(0);
  });
});
