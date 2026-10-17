import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

import { TenantChargesSection } from "./tenant-charges";
import type { TenantPortalCharge, TenantPortalCharges } from "@/types/api";

function charge(id: string, status: TenantPortalCharge["status"], start: string, end: string, paidOn: string | null = null): TenantPortalCharge {
  return { id, period_start: start, period_end: end, billing_cycle: "monthly", amount_rp: 8910, lines: [], status, due_on: start, paid_on: paidOn };
}

const data: TenantPortalCharges = {
  items: [
    charge("c4", "open", "2026-10-15", "2026-11-15"),
    charge("c3", "overdue", "2026-09-15", "2026-10-15"),
    charge("c2", "waived", "2026-08-15", "2026-09-15"),
    charge("c1", "paid", "2026-07-15", "2026-08-15", "2026-07-21"),
  ],
  open: { count: 2, amount_rp: 17820 },
  overdue: { count: 1, amount_rp: 8910 },
  payment_term_days: 30,
};

describe("TenantChargesSection", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockResolvedValue(data);
  });

  it("zeigt die Forderungen mit allen vier Status", async () => {
    render(<TenantChargesSection tenantId="t1" />);
    expect(await screen.findByText("Abrechnung")).toBeInTheDocument();
    expect(browserApiFetchMock).toHaveBeenCalledWith("/api/tenants/t1/charges");
    for (const label of ["Offen", "Überfällig", "Erlassen", "Bezahlt"]) expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText(/davon überfällig/)).toBeInTheDocument();
    expect(screen.getByText("21.07.2026")).toBeInTheDocument();
  });

  it("bleibt ohne Forderungen ausgeblendet", async () => {
    browserApiFetchMock.mockResolvedValue({ ...data, items: [], open: { count: 0, amount_rp: 0 }, overdue: { count: 0, amount_rp: 0 } });
    const { container } = render(<TenantChargesSection tenantId="t1" />);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container).toBeEmptyDOMElement();
  });
});
