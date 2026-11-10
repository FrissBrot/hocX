import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { AgendaItem, AgendaTemplateOption } from "@/types/api";

const api = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (url: string, init?: unknown) => api(url, init) }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
// Tiptap rendert in jsdom nicht zuverlässig (wie in todo-edit-modal.test.tsx gemockt)
vi.mock("@/components/ui/rich-text-editor", () => ({
  RichTextEditor: ({ value, onChange, readOnly }: { value: string; onChange: (value: string) => void; readOnly?: boolean }) =>
    <textarea aria-label="Text-Editor" value={value} readOnly={readOnly} onChange={(event) => onChange(event.target.value)} />,
}));

import { AgendaListView } from "./agenda-list-view";
import { AgendaItemModal } from "./agenda-item-modal";

const templates: AgendaTemplateOption[] = [
  { id: "tpl-1", name: "Vorstand", points: [{ id: "pt-1", name: "Finanzen" }, { id: "pt-2", name: "Varia" }] },
  { id: "tpl-2", name: "GV", points: [{ id: "pt-3", name: "Wahlen" }] },
];

function item(overrides: Partial<AgendaItem> = {}): AgendaItem {
  return {
    id: "a-1", title: "Neue Kasse", body: "Die alte ist kaputt", template_id: "tpl-1", template_name: "Vorstand",
    template_element_id: "pt-1", template_element_name: "Finanzen", schedule_kind: "next_meeting", scheduled_month: null,
    earliest_date: "2026-10-24", postponed_count: 0, state: "scheduled",
    protocol: { id: "p-1", protocol_number: "V-12", title: null, protocol_date: "2026-11-03", status: "geplant" },
    is_bound: false, can_edit: true, created_by_name: "Anna Muster", created_at: "2026-10-24T10:00:00Z", updated_at: "2026-10-24T10:00:00Z",
    ...overrides,
  };
}

beforeEach(() => vi.clearAllMocks());

it("lists open items with creator, place and target protocol; treated ones behind the filter", () => {
  render(<AgendaListView items={[item(), item({ id: "a-2", title: "Alt", state: "treated", is_bound: true })]} templates={templates} preferredTemplateId={null} canEdit />);
  const rows = screen.getAllByRole("row").slice(1);
  expect(rows).toHaveLength(1);
  const row = within(rows[0]);
  expect(row.getByText("Neue Kasse")).toBeTruthy();
  expect(row.getByText("Anna Muster")).toBeTruthy();
  expect(row.getByText("Finanzen")).toBeTruthy();
  expect(row.getByText("Protokoll V-12 · 03.11.2026")).toBeTruthy();

  fireEvent.click(screen.getByRole("tab", { name: /Behandelt/ }));
  expect(screen.getByText("Alt")).toBeTruthy();
  expect(screen.queryByText("Neue Kasse")).toBeNull();
});

it("preselects the remembered template and stores the choice after creating", async () => {
  api.mockImplementation((url: string) => Promise.resolve(url === "/api/agenda-items" ? item({ id: "a-9", template_id: "tpl-2" }) : undefined));
  const saved = vi.fn();
  const remembered = vi.fn();
  render(<AgendaItemModal templates={templates} preferredTemplateId="tpl-2" canEdit onClose={vi.fn()} onSaved={saved} onTemplateRemembered={remembered} />);

  expect(screen.getByText("GV")).toBeTruthy();
  expect(screen.getByText("Wahlen")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Titel"), { target: { value: "Neuwahl Kassier" } });
  fireEvent.click(screen.getByRole("button", { name: "Erfassen" }));

  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  const [, init] = api.mock.calls.find(([url]) => url === "/api/agenda-items")!;
  expect(JSON.parse((init as { body: string }).body)).toMatchObject({
    template_id: "tpl-2", template_element_id: "pt-3", title: "Neuwahl Kassier", schedule: { kind: "next_meeting" },
  });
  await waitFor(() => expect(remembered).toHaveBeenCalledWith("tpl-2"));
  expect(api).toHaveBeenCalledWith("/api/agenda-items/template-preference", expect.objectContaining({ method: "PUT" }));
});

it("month schedule sends the chosen month", async () => {
  api.mockResolvedValue(item());
  render(<AgendaItemModal templates={templates} preferredTemplateId={null} canEdit onClose={vi.fn()} onSaved={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Titel"), { target: { value: "Budget" } });
  fireEvent.click(screen.getByRole("tab", { name: "Monat" }));
  fireEvent.click(screen.getByRole("button", { name: "Erfassen" }));
  await waitFor(() => expect(api).toHaveBeenCalled());
  const body = JSON.parse((api.mock.calls[0][1] as { body: string }).body);
  expect(body.template_id).toBe("tpl-1");
  expect(body.schedule.kind).toBe("month");
  expect(body.schedule.month).toMatch(/^\d{4}-\d{2}-01$/);
});

it("bound items only allow title and text; frozen items are read-only", () => {
  const { unmount } = render(
    <AgendaItemModal item={item({ is_bound: true })} templates={templates} canEdit onClose={vi.fn()} onSaved={vi.fn()} />
  );
  expect(screen.getByText(/Steht im Protokoll V-12/)).toBeTruthy();
  expect(screen.queryByRole("tab", { name: "Monat" })).toBeNull();
  expect(screen.getByText("Erstellt von Anna Muster am 24.10.2026")).toBeTruthy();
  unmount();

  render(<AgendaItemModal item={item({ is_bound: true, can_edit: false })} templates={templates} canEdit onClose={vi.fn()} onSaved={vi.fn()} />);
  expect(screen.getByText(/abgeschlossenen Protokoll/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Speichern" })).toBeNull();
});
