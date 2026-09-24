import { render, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const { fetchMock, editorMock, settingsMock } = vi.hoisted(() => ({
  fetchMock: vi.fn(), editorMock: vi.fn(() => null), settingsMock: vi.fn(() => null),
}));
vi.mock("@/lib/api/server", () => ({
  backendFetchWithSession: fetchMock,
  requireSession: async () => ({ current_role: "admin", current_tenant: { id: "first-tenant" } }),
  // Mirrors the real resolveManageableTenant (lib/api/server.ts) closely enough for this test:
  // picks the requested tenant by id out of the (mocked) manageable-tenants list, falling back
  // to the first one.
  resolveManageableTenant: async (session: { current_tenant?: { id: string } | null }, tenantId?: string) => {
    const manageableTenants = await fetchMock("/api/tenants");
    const requestedId = tenantId ? tenantId : session.current_tenant?.id;
    return manageableTenants.find((t: { id: string }) => t.id === requestedId) ?? manageableTenants[0];
  },
}));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));
vi.mock("@/components/ui/app-shell", () => ({ AppShell: ({ children }: any) => children }));
vi.mock("@/components/protocol/protocol-editor", () => ({ ProtocolEditor: editorMock }));
vi.mock("@/components/protocol/protocol-builder", () => ({ ProtocolOverview: () => null }));
vi.mock("@/components/settings/tenant-general-settings", () => ({ TenantGeneralSettings: settingsMock }));

import ProtocolDetailPage from "./protocols/[id]/page";
import TenantSettingsPage from "./tenant-settings/page";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("loads snapshot references using public UUIDs and retains snapshot cache keys", async () => {
  const listId = "01a067ae-27a5-7e49-986a-5606a4cdda10";
  const accountId = "01a067ae-27a5-7e49-986a-5606a4cdda11";
  const entries = [{ id: "entry" }];
  const transactions = [{ id: "transaction" }];
  fetchMock.mockImplementation(async (url: string) => {
    if (url === "/api/protocols/protocol") return { id: "protocol", template_id: "template", status: "geplant" };
    if (url === "/api/protocols/protocol/elements") return [{ blocks: [{
      element_type_code: "finance_transactions",
      configuration_snapshot_json: { linked_list_id: 42, finance_account_id: 73 },
      public_reference_ids: { lists: { "42": listId }, finance_accounts: { "73": accountId } },
    }] }];
    if (url === `/api/lists/${listId}/entries`) return entries;
    if (url === `/api/finance/accounts/${accountId}/transactions`) return transactions;
    return [];
  });
  render(await ProtocolDetailPage({ params: Promise.resolve({ id: "protocol" }) }));
  expect(fetchMock).toHaveBeenCalledWith(`/api/lists/${listId}/entries`);
  expect(fetchMock).toHaveBeenCalledWith(`/api/finance/accounts/${accountId}/transactions`);
  expect(fetchMock).not.toHaveBeenCalledWith("/api/lists/42/entries");
  expect(fetchMock).not.toHaveBeenCalledWith("/api/finance/accounts/73/transactions");
  const props = editorMock.mock.calls[0][0];
  expect(props.initialListEntries["42"]).toEqual(entries);
  expect(props.initialListEntries[listId]).toEqual(entries);
  expect(props.initialFinanceTransactions["73"]).toEqual(transactions);
  expect(props.initialFinanceTransactions[accountId]).toEqual(transactions);
});

it("selects the requested tenant UUID instead of falling back to the first tenant", async () => {
  const selected = { id: "01a067ae-27a5-7e49-986a-5606a4cdda10", name: "Selected" };
  fetchMock.mockResolvedValue([{ id: "first-tenant" }, selected]);
  render(await TenantSettingsPage({ searchParams: Promise.resolve({ tenantId: selected.id }) }));
  expect(settingsMock.mock.calls[0][0].initialTenant).toEqual(selected);
});
