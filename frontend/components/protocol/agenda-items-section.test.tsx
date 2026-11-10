import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ProtocolAgendaItem } from "@/types/api";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (url: string, init?: unknown) => api(url, init) }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
vi.mock("@/components/ui/rich-text-editor", () => ({
  RichTextEditor: ({ value, onChange, readOnly }: { value: string; onChange: (value: string) => void; readOnly?: boolean }) =>
    <textarea aria-label="Text-Editor" value={value} readOnly={readOnly} onChange={(event) => onChange(event.target.value)} />,
}));

import { AgendaItemsSection } from "./agenda-items-section";

const item: ProtocolAgendaItem = { id: "a-1", title: "Neue Kasse", body: "", protocol_element_id: "el-1", postponed_count: 1, can_edit: true };

beforeEach(() => {
  vi.useFakeTimers();
  api.mockResolvedValue({ title: "Neue Kasse kaufen", body: "Offerte liegt vor" });
});
afterEach(() => vi.useRealTimers());

it("saves title and text together after a short pause, without creator", async () => {
  const changed = vi.fn();
  render(<AgendaItemsSection items={[item]} isReadOnly={false} onChanged={changed} onRemoved={vi.fn()} onPostpone={vi.fn()} />);
  expect(screen.getByText("1 × vertagt")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Titel des Anliegens"), { target: { value: "Neue Kasse kaufen" } });
  fireEvent.change(screen.getByLabelText("Text-Editor"), { target: { value: "Offerte liegt vor" } });
  expect(api).not.toHaveBeenCalled();
  await act(async () => { await vi.advanceTimersByTimeAsync(900); });
  expect(api).toHaveBeenCalledOnce();
  expect(api.mock.calls[0][0]).toBe("/api/agenda-items/a-1");
  expect(JSON.parse((api.mock.calls[0][1] as { body: string }).body)).toEqual({ title: "Neue Kasse kaufen", body: "Offerte liegt vor" });
  expect(changed).toHaveBeenCalledWith(expect.objectContaining({ id: "a-1", title: "Neue Kasse kaufen" }));
});

it("is read-only without actions in a closed protocol and renders nothing when empty", () => {
  const { container, rerender } = render(<AgendaItemsSection items={[]} isReadOnly={false} onChanged={vi.fn()} onRemoved={vi.fn()} onPostpone={vi.fn()} />);
  expect(container.innerHTML).toBe("");
  rerender(<AgendaItemsSection items={[{ ...item, can_edit: false }]} isReadOnly={false} heading="Weitere Anliegen" onChanged={vi.fn()} onRemoved={vi.fn()} onPostpone={vi.fn()} />);
  expect(screen.getByText("Weitere Anliegen")).toBeTruthy();
  expect((screen.getByLabelText("Titel des Anliegens") as HTMLInputElement).readOnly).toBe(true);
  expect(screen.queryByLabelText("Aktionen für das Anliegen")).toBeNull();
});
