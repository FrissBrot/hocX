import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ParticipantSummary, TodoListItem } from "@/types/api";
const api = vi.hoisted(() => vi.fn());
const sideApi = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => vi.fn());
// Notizen/Dateien (GET details) und die Dateisuche laufen über sideApi, damit die Zählungen
// der Todo-Anfragen in den bestehenden Tests unverändert bleiben.
vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (url: string, init?: { method?: string }) =>
    (url.endsWith('/details') && !init?.method) || url.startsWith('/api/files') ? sideApi(url, init) : api(url, init),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
// Tiptap rendert in jsdom nicht zuverlässig (wie in element-definition-manager.test.tsx gemockt)
vi.mock("@/components/ui/rich-text-editor", () => ({
  RichTextEditor: ({ value, onChange, readOnly }: { value: string; onChange: (value: string) => void; readOnly?: boolean }) =>
    <textarea aria-label="Notizen-Editor" value={value} readOnly={readOnly} onChange={(event) => onChange(event.target.value)} />,
}));
import { TodoEditModal } from "./todo-edit-modal";
const todo = { id: 'todo-1', task: 'Bankvollmacht einreichen', tags: ['Finanzen'], todo_status_id: 1, todo_status_code: 'open', assigned_participant_id: null, protocol_id: null } as TodoListItem;
const saved = vi.fn();
const closed = vi.fn();
function mount(canEdit = true) { render(<TodoEditModal todo={todo} canEdit={canEdit} participants={[]} tagSuggestions={[]} onSaved={saved} onClose={closed} onDeleted={vi.fn()} />); }
const files = [
  { id: 'file-1', original_name: 'Vollmacht.pdf', mime_type: 'application/pdf', file_size_bytes: 2048, content_url: '/api/stored-files/file-1/content' },
  { id: 'file-2', original_name: 'Budget.xlsx', mime_type: null, file_size_bytes: null, content_url: '/api/stored-files/file-2/content' },
];
beforeEach(() => {
  sideApi.mockImplementation((url: string) => Promise.resolve(url.startsWith('/api/files') ? files : { notes: '', files: [] }));
});
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
it('shows notes and linked files from the details endpoint', async () => {
  sideApi.mockImplementation(() => Promise.resolve({ notes: '**Bank** anrufen', files: [files[0]] }));
  mount();
  expect(await screen.findByRole('link', { name: /Vollmacht.pdf/ })).toHaveAttribute('href', '/api/stored-files/file-1/content');
  expect(screen.getByLabelText('Notizen-Editor')).toHaveValue('**Bank** anrufen');
});
it('saves changed notes as markdown', async () => {
  mount();
  fireEvent.change(await screen.findByLabelText('Notizen-Editor'), { target: { value: '- Punkt' } });
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(JSON.parse(api.mock.calls[1][1].body)).toEqual({ notes: '- Punkt' });
});
it('skips the details request when notes and files are unchanged', async () => {
  mount();
  await screen.findByLabelText('Hochgeladene Datei suchen …');
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(api).toHaveBeenCalledOnce();
});
it('links an uploaded file and saves it with the todo', async () => {
  api.mockResolvedValue(todo);
  mount();
  const search = await screen.findByLabelText('Hochgeladene Datei suchen …');
  fireEvent.focus(search);
  fireEvent.mouseDown(await screen.findByRole('option', { name: /Budget.xlsx/ }));
  expect(screen.getByRole('link', { name: /Budget.xlsx/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(api).toHaveBeenCalledTimes(2);
  expect(api.mock.calls[1][0]).toBe('/api/protocol-todos/todo-1/details');
  expect(JSON.parse(api.mock.calls[1][1].body)).toEqual({ file_ids: ['file-2'] });
});
