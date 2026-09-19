import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { TodoListItem } from "@/types/api";
const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ browserApiFetch: api }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
import { TodoEditModal } from "./todo-edit-modal";
const todo = { id: 'todo-1', task: 'Bankvollmacht einreichen', tags: ['Finanzen'], todo_status_id: 1, todo_status_code: 'open', assigned_participant_id: null, protocol_id: null } as TodoListItem;
const saved = vi.fn();
const closed = vi.fn();
function mount(canEdit = true) { render(<TodoEditModal todo={todo} canEdit={canEdit} participants={[]} tagSuggestions={[]} onSaved={saved} onClose={closed} onDeleted={vi.fn()} />); }
beforeEach(() => { vi.clearAllMocks(); api.mockResolvedValue({ ...todo, task: 'Neue Aufgabe', todo_status_id: 2, todo_status_code: 'in_progress' }); });
it('discards edits on cancel without writing to the API', () => {
  mount();
  fireEvent.change(screen.getByLabelText('Aufgabe'), { target: { value: 'Neue Aufgabe' } });
  fireEvent.click(screen.getByRole('button', { name: 'In Arbeit' }));
  fireEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
  expect(closed).toHaveBeenCalledOnce();
  expect(api).not.toHaveBeenCalled();
});
it('saves the draft in one request', async () => {
  mount();
  fireEvent.change(screen.getByLabelText('Aufgabe'), { target: { value: 'Neue Aufgabe' } });
  fireEvent.click(screen.getByRole('button', { name: 'In Arbeit' }));
  expect(api).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(JSON.parse(api.mock.calls[0][1].body)).toMatchObject({ task: 'Neue Aufgabe', todo_status_id: 2, tags: ['Finanzen'] });
  expect(api).toHaveBeenCalledOnce();
});
it('keeps the dialog open if saving fails', async () => {
  api.mockRejectedValue(new Error('Fehler'));
  mount();
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Speichern' })).toBeEnabled());
  expect(saved).not.toHaveBeenCalled();
  expect(closed).not.toHaveBeenCalled();
});
it('prevents editing with read-only access', () => {
  mount(false);
  expect(screen.getByLabelText('Aufgabe')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'In Arbeit' })).toBeDisabled();
  expect(screen.queryByRole('button', { name: 'Speichern' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Todo löschen' })).not.toBeInTheDocument();
});
