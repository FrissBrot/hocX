import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// recharts' ResponsiveContainer braucht ResizeObserver, den jsdom nicht kennt.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

const browserApiFetchMock = vi.fn();
const showToast = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => showToast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn(async () => true) }));

import { AdminCashflow } from "./admin-cashflow";
import { CashflowCost, CashflowOverview, TenantChargePage } from "@/types/api";

function overview(): CashflowOverview {
  return {
    year: 2026,
    years: [2026, 2027],
    today: "2026-10-17",
    months: Array.from({ length: 12 }, (_, index) => ({
      month: `2026-${String(index + 1).padStart(2, "0")}`,
      income_rp: index === 0 ? 4900 : 0,
      fixed_rp: 1500,
      percent_rp: index === 0 ? 142 : 0,
      planned_fixed_rp: 1000,
      planned_percent_rp: 0,
      open_rp: 0,
      is_future: index > 9,
    })),
    year_to_date: { income_rp: 4900, expenses_rp: 15142, planned_expenses_rp: 10000 },
    all_time: { income_rp: 4900, expenses_rp: 15142, planned_expenses_rp: 10000 },
    run_rate: { income_rp: 4900, fixed_rp: 1500, percent_rp: 142, planned_fixed_rp: 1000, planned_percent_rp: 0, paying_tenants: 1 },
    open: { count: 2, amount_rp: 9800 },
    waived: { count: 0, amount_rp: 0 },
    overdue: { count: 1, amount_rp: 4900 },
  };
}

const cost: CashflowCost = {
  id: "c1",
  name: "Hetzner Server",
  kind: "fixed",
  amount_rp: 1500,
  percent_bp: null,
  interval: "monthly",
  start_date: "2026-01-01",
  end_date: null,
  status: "active",
  note: null,
  next_due_on: "2026-11-01",
  monthly_equivalent_rp: 1500,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const charges: TenantChargePage = {
  items: [
    {
      id: "ch1",
      tenant_id: "t1",
      tenant_name: "Turnverein Seedorf",
      period_start: "2026-10-01",
      period_end: "2026-11-01",
      billing_cycle: "monthly",
      amount_rp: 4900,
      lines: [{ kind: "plan", label: "Verein", amount_rp: 4900 }],
      status: "open",
      paid_on: null,
      note: null,
      updated_at: "2026-10-01T00:00:00Z",
      due_on: "2026-10-31",
      is_overdue: false,
    },
  ],
  total: 1,
  totals: { open: { count: 1, amount_rp: 4900 }, paid: { count: 0, amount_rp: 0 }, waived: { count: 0, amount_rp: 0 }, overdue: { count: 0, amount_rp: 0 } },
};

describe("AdminCashflow", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToast.mockReset();
    browserApiFetchMock.mockImplementation(async (path: string) => {
      if (path.startsWith("/api/admin/cashflow/costs")) return [cost];
      if (path.startsWith("/api/admin/cashflow/charges")) return charges;
      return overview();
    });
  });

  it("zeigt Einnahmen, Ausgaben und Bilanz", () => {
    render(<AdminCashflow initialOverview={overview()} />);
    expect(screen.getByText("Einnahmen 2026")).toBeInTheDocument();
    expect(screen.getByText("Bilanz gesamt")).toBeInTheDocument();
    expect(screen.getAllByText("Prognose")).toHaveLength(2);
  });

  it("markiert eine Forderung als bezahlt", async () => {
    render(<AdminCashflow initialOverview={overview()} />);
    fireEvent.click(screen.getByRole("tab", { name: "Forderungen" }));
    await screen.findByText("Turnverein Seedorf");
    fireEvent.click(screen.getByRole("button", { name: /Offen/ }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /Bezahlt/ }));
    await waitFor(() =>
      expect(browserApiFetchMock).toHaveBeenCalledWith("/api/admin/cashflow/charges/ch1", { method: "PATCH", body: JSON.stringify({ status: "paid" }) })
    );
  });

  it("legt eine prozentuale Ausgabe an", async () => {
    render(<AdminCashflow initialOverview={overview()} />);
    fireEvent.click(screen.getByRole("button", { name: "Ausgabe erfassen" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("radio", { name: /Prozentual/ }));
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "TWINT" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: /Prozentsatz/ }), { target: { value: "1.3" } });
    fireEvent.click(screen.getByRole("button", { name: "Erfassen" }));
    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith("/api/admin/cashflow/costs", expect.objectContaining({ method: "POST" })));
    const call = browserApiFetchMock.mock.calls.find(([path, init]) => path === "/api/admin/cashflow/costs" && init?.method === "POST");
    expect(JSON.parse(call![1].body)).toMatchObject({ name: "TWINT", kind: "percent", percent_bp: 130, amount_rp: null, interval: null });
    expect(dialog).toBeTruthy();
  });
});
