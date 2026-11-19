import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ browserApiFetch: vi.fn() }));

import { ChargeFilter, daysUntil, TenantInvoiceList, TenantInvoicePanel, TenantInvoiceSummary, TenantOverdueBanner } from "./tenant-charges";
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

function List({ onOpen = vi.fn() }: { onOpen?: (charge: TenantPortalCharge) => void }) {
  const [filter, setFilter] = useState<ChargeFilter>("all");
  return <TenantInvoiceList charges={data} filter={filter} onFilterChange={setFilter} onOpen={onOpen} />;
}

describe("TenantInvoiceList", () => {
  it("zeigt alle vier Status, Monatsnamen und filtert offen/erledigt", () => {
    render(<List />);
    expect(screen.getByRole("heading", { name: "Alle Rechnungen" })).toBeInTheDocument();
    for (const label of ["Offen", "Überfällig", "Erlassen", "Bezahlt"]) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Oktober 2026" })).toBeInTheDocument();
    expect(screen.getByText("bezahlt am 09.07.2026")).toBeInTheDocument();
    // Kein PDF-Download in der Liste (bewusst weggelassen)
    expect(screen.queryByText(/PDF/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Erledigt/ }));
    expect(screen.queryByText("01.10.2026 – 31.10.2026")).not.toBeInTheDocument();
    expect(screen.getByText("01.07.2026 – 31.07.2026")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /^Offen/ }));
    expect(screen.getByText("01.10.2026 – 31.10.2026")).toBeInTheDocument();
    expect(screen.queryByText("01.07.2026 – 31.07.2026")).not.toBeInTheDocument();
  });

  it("öffnet eine Rechnung per Klick auf die Zeile", () => {
    const onOpen = vi.fn();
    render(<List onOpen={onOpen} />);
    fireEvent.click(screen.getByRole("button", { name: "September 2026" }));
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: "c3" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("nennt den Rabatt einer Rechnung", () => {
    const discounted: TenantPortalCharge = {
      ...charge("d1", "open", "2026-10-01", "2026-11-01", "2099-10-31"),
      lines: [
        { kind: "plan", label: "Verein", amount_rp: 24990 },
        { kind: "discount", label: "discount", amount_rp: -5090, percent: 20.3681 },
      ],
    };
    render(<TenantInvoiceList charges={{ ...data, items: [discounted] }} filter="all" onFilterChange={() => undefined} onOpen={() => undefined} />);
    expect(screen.getByText(/inkl\. 20\.37 % Rabatt \(−CHF 50\.90\)/)).toBeInTheDocument();
  });
});

describe("TenantInvoicePanel", () => {
  it("zeigt Periode, Fälligkeit, Positionen und Total, ohne PDF/QR", () => {
    const withLines: TenantPortalCharge = {
      ...charge("p1", "paid", "2026-07-01", "2026-08-01", "2026-07-31", "2026-07-09"),
      lines: [
        { kind: "plan", label: "Verein", amount_rp: 24990 },
        { kind: "feature", label: "Abgabebox", amount_rp: 590 },
        { kind: "discount", label: "discount", amount_rp: -5680, percent: 22.2 },
        { kind: "storage_package", label: "Speicher 10 GB", amount_rp: 0, quantity: 2 },
      ],
    };
    render(<TenantInvoicePanel charge={withLines} onClose={vi.fn()} />);
    const dialog = screen.getByRole("dialog", { name: "Rechnung Juli 2026" });
    expect(within(dialog).getByText("01.07.2026 – 31.07.2026")).toBeInTheDocument();
    expect(within(dialog).getByText("31.07.2026")).toBeInTheDocument();
    expect(within(dialog).getByText("09.07.2026")).toBeInTheDocument();
    expect(within(dialog).getByText("Rabatt 22.2 %")).toBeInTheDocument();
    expect(within(dialog).getByText("Speicher 10 GB × 2")).toBeInTheDocument();
    expect(within(dialog).getByText("CHF 199.00")).toBeInTheDocument();
    expect(within(dialog).queryByText(/PDF|QR/)).not.toBeInTheDocument();
  });

  it("rendert ohne Rechnung nichts", () => {
    const { container } = render(<TenantInvoicePanel charge={null} onClose={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("TenantInvoiceSummary", () => {
  it("nennt Offen, nächste Rechnung und Bezahltes im Jahr", () => {
    render(<TenantInvoiceSummary charges={data} nextAmountRp={19900} today={new Date(2026, 9, 17)} />);
    expect(screen.getByText("CHF 398.00")).toBeInTheDocument();
    expect(screen.getByText("2 Rechnungen · 1 überfällig")).toBeInTheDocument();
    expect(screen.getByText("am 01.11.2026")).toBeInTheDocument();
    expect(screen.getByText("Bezahlt 2026")).toBeInTheDocument();
    expect(screen.getByText("1 Rechnung")).toBeInTheDocument();
  });

  it("zeigt ohne genauen Betrag nur das Datum der nächsten Rechnung", () => {
    render(<TenantInvoiceSummary charges={data} nextAmountRp={null} today={new Date(2026, 9, 17)} />);
    expect(screen.getByText("01.11.2026")).toBeInTheDocument();
  });
});

describe("TenantOverdueBanner", () => {
  it("nennt Rechnung und Betrag und öffnet die überfällige Rechnung", () => {
    const onOpenCharge = vi.fn();
    render(<TenantOverdueBanner charges={data} onOpenCharge={onOpenCharge} onShowOpen={vi.fn()} />);
    expect(screen.getByText("Rechnung September 2026 überfällig · CHF 199.00")).toBeInTheDocument();
    expect(screen.getByText(/War am 01.10.2026 fällig/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rechnung öffnen" }));
    expect(onOpenCharge).toHaveBeenCalledWith(expect.objectContaining({ id: "c3" }));
  });

  it("zeigt bei mehreren überfälligen Rechnungen die offenen an", () => {
    const onShowOpen = vi.fn();
    const many = { ...data, items: data.items.map((c) => (c.id === "c4" ? { ...c, status: "overdue" as const } : c)), overdue: { count: 2, amount_rp: 39800 } };
    render(<TenantOverdueBanner charges={many} onOpenCharge={vi.fn()} onShowOpen={onShowOpen} />);
    expect(screen.getByText("2 Rechnungen überfällig · CHF 398.00")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Offene anzeigen" }));
    expect(onShowOpen).toHaveBeenCalled();
  });

  it("bleibt ohne überfällige Rechnungen leer", () => {
    const { container } = render(<TenantOverdueBanner charges={{ ...data, items: data.items.filter((c) => c.status !== "overdue") }} onOpenCharge={vi.fn()} onShowOpen={vi.fn()} />);
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
