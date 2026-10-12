import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ParticipantSummary, TodoListItem } from "@/types/api";
const api = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ browserApiFetch: api }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
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
it('sets a custom due date for a standalone todo and saves all due fields', async () => {
  api.mockResolvedValueOnce({ events: [], next_event_id: null, tag_filter: null });
  mount();
  fireEvent.click(screen.getByRole('button', { name: /Kein Enddatum/ }));
  const input = await screen.findByLabelText('Eigenes Datum');
  fireEvent.change(input, { target: { value: '25.10.2026' } });
  expect(screen.getByRole('button', { name: /25.10.2026/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(JSON.parse(api.mock.calls[1][1].body)).toMatchObject({ due_date: '2026-10-25', due_event_id: null, due_marker: null });
});
it('shows package origin and preserves all assignees when saving', async () => {
  const people = [{ id: 'anna', display_name: 'Anna' }, { id: 'ben', display_name: 'Ben' }];
  render(<TodoEditModal todo={{ ...todo, task_package_name: 'Scharleitung', assigned_participant_id: 'anna', assigned_participant_ids: ['anna', 'ben'] }} canEdit participants={people as ParticipantSummary[]} tagSuggestions={[]} onSaved={saved} onClose={closed} onDeleted={vi.fn()} />);
  expect(screen.getByText('Scharleitung')).toBeInTheDocument();
  expect(screen.queryByText('Manuell erstellt')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Zugewiesen an' })).toHaveTextContent('Anna, Ben');
  fireEvent.click(screen.getByRole('button', { name: 'Zugewiesen an' }));
  expect(screen.getByRole('option', { name: /Ben/ })).toHaveAttribute('aria-selected', 'true');
  fireEvent.click(screen.getByRole('option', { name: /Ben/ }));
  fireEvent.click(screen.getByRole('option', { name: /Ben/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(JSON.parse(api.mock.calls[0][1].body)).toMatchObject({ assigned_participant_ids: ['anna', 'ben'] });
});
it('allows selecting and clearing multiple assignees', async () => {
  const people = [{ id: 'anna', display_name: 'Anna' }, { id: 'ben', display_name: 'Ben' }];
  render(<TodoEditModal todo={todo} canEdit participants={people as ParticipantSummary[]} tagSuggestions={[]} onSaved={saved} onClose={closed} onDeleted={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Zugewiesen an' }));
  for (const name of ['Anna', 'Ben', 'Anna', 'Ben']) fireEvent.click(screen.getByRole('option', { name: new RegExp(name) }));
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(JSON.parse(api.mock.calls[0][1].body).assigned_participant_ids).toEqual([]);
});
