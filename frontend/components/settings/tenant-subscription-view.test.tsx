import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
let search = new URLSearchParams("tenantId=t1");
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/tenant-settings/abo",
  useSearchParams: () => search,
}));

const fetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (path: string) => fetchMock(path) }));

import { TenantSubscriptionView } from "./tenant-subscription-view";
import type { TenantPortalCharges, TenantSubscription, TenantSummary } from "@/types/api";

const tenant = { id: "t1", name: "Verein" } as TenantSummary;

const subscription: TenantSubscription = {
  plan_code: "standard",
  plan_name: "Standard",
  billing_cycle: "monthly",
  plan_price_monthly_rp: 14900,
  plan_price_yearly_rp: 149000,
  included_user_limit: null,
  included_storage_bytes: null,
  user_limit_override: null,
  effective_user_limit: null,
  user_count: 4,
  storage_used_bytes: 0,
  storage_quota_bytes: null,
  package_storage_bytes: 0,
  features: [
    { code: "finance", name: "Finanzen", description: null, standalone_price_monthly_rp: 790, included_in_plan: true },
    { code: "abgabebox", name: "Abgabebox", description: "Öffentliche Upload-Seite", standalone_price_monthly_rp: 590, included_in_plan: false },
    { code: "custom_roles", name: "Eigene Rollen", description: null, standalone_price_monthly_rp: 790, included_in_plan: false, read_only: true },
  ],
  estimated_monthly_cost_rp: 15490,
  estimated_yearly_cost_rp: 156080,
  discount_percent: 0,
  list_monthly_cost_rp: 15490,
  list_yearly_cost_rp: 156080,
};

const charges: TenantPortalCharges = {
  items: [
    { id: "c2", period_start: "2026-10-01", period_end: "2026-11-01", billing_cycle: "monthly", amount_rp: 15490, lines: [], status: "overdue", due_on: "2026-10-31", paid_on: null },
    { id: "c1", period_start: "2026-09-01", period_end: "2026-10-01", billing_cycle: "monthly", amount_rp: 15490, lines: [], status: "paid", due_on: "2026-10-01", paid_on: "2026-09-10" },
  ],
  open: { count: 1, amount_rp: 15490 },
  overdue: { count: 1, amount_rp: 15490 },
  payment_term_days: 30,
};

beforeEach(() => {
  replace.mockReset();
  search = new URLSearchParams("tenantId=t1");
  fetchMock.mockImplementation(async (path: string) => {
    if (path.endsWith("/subscription")) return subscription;
    if (path.endsWith("/charges")) return charges;
    if (path === "/api/users") return [];
    throw new Error(path);
  });
});

describe("TenantSubscriptionView", () => {
  it("zeigt Kostenaufstellung mit enthaltenen Funktionen, Zusatzmodulen nach Modul und Total", async () => {
    render(<TenantSubscriptionView initialTenant={tenant} />);
    expect(await screen.findByText("Grundplan Standard")).toBeInTheDocument();
    const included = screen.getByRole("list", { name: "Im Plan enthalten" });
    expect(within(included).getByText("Finanzen")).toBeInTheDocument();
    expect(screen.getByText("Abgaben")).toBeInTheDocument();
    expect(screen.getByText("+ CHF 5.90")).toBeInTheDocument();
    expect(screen.getByText("Nur lesen")).toBeInTheDocument();
    expect(screen.getByText("1 Zusatzmodul aktiv")).toBeInTheDocument();
    expect(screen.getAllByText("CHF 154.90").length).toBeGreaterThan(0);
    // Reiter «Rechnungen» mit rotem Zähler, weil eine Rechnung überfällig ist
    const invoicesTab = await screen.findByRole("tab", { name: /Rechnungen/ });
    expect(within(invoicesTab).getByText("1")).toHaveClass("tabs-count-danger");
  });

  it("wechselt den Reiter über ?tab=invoices", async () => {
    render(<TenantSubscriptionView initialTenant={tenant} />);
    fireEvent.click(await screen.findByRole("tab", { name: /Rechnungen/ }));
    expect(replace).toHaveBeenCalledWith("/tenant-settings/abo?tenantId=t1&tab=invoices", { scroll: false });
  });

  it("öffnet aus dem Überfällig-Hinweis das Seitenpanel der Rechnung", async () => {
    search = new URLSearchParams("tab=invoices");
    render(<TenantSubscriptionView initialTenant={tenant} />);
    expect(await screen.findByRole("heading", { name: "Alle Rechnungen" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rechnung öffnen" }));
    expect(await screen.findByRole("dialog", { name: "Rechnung Oktober 2026" })).toBeInTheDocument();
  });
});

describe("TenantSubscriptionView – Plätze", () => {
  it("zieht offene Einladungen von den freien Plätzen ab (sie zählen zum Benutzerlimit)", async () => {
    fetchMock.mockImplementation(async (path: string) => {
      if (path.endsWith("/subscription")) return { ...subscription, effective_user_limit: 5, user_count: 3, pending_invite_count: 2 };
      if (path.endsWith("/charges")) return charges;
      if (path === "/api/users") return [];
      throw new Error(path);
    });
    render(<TenantSubscriptionView initialTenant={tenant} />);
    expect(await screen.findByText(/0 Plätze frei/)).toBeInTheDocument();
    expect(screen.getByText(/2 offene Einladungen belegen Plätze/)).toBeInTheDocument();
  });

  it("nennt die Konten in der Avatarreihe mit Namen statt nur mit Initialen (Screenreader)", async () => {
    const users = Array.from({ length: 10 }, (_, index) => ({ id: `u${index}`, display_name: `Person ${index}` }));
    fetchMock.mockImplementation(async (path: string) => {
      if (path.endsWith("/subscription")) return subscription;
      if (path.endsWith("/charges")) return charges;
      if (path === "/api/users") return users;
      throw new Error(path);
    });
    render(<TenantSubscriptionView initialTenant={tenant} />);
    const list = await screen.findByRole("list", { name: "Konten" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(9);
    expect(items[0]).toHaveTextContent("Person 0");
    expect(items[8]).toHaveTextContent("2 weitere Konten");
  });
});
