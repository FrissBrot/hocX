import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ParticipantSummary, TodoListItem } from "@/types/api";
const api = vi.hoisted(() => vi.fn());
const sideApi = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => vi.fn());
// Notizen/Dateien (GET details) und die Dateisuche laufen über sideApi, damit die Zählungen
// der Todo-Anfragen in den bestehenden Tests unverändert bleiben.
vi.mock("@/lib/api/client", () => ({
  ApiError: class ApiError extends Error { constructor(message: string, public kind?: string, public status?: number, public detail?: unknown) { super(message); } },
  browserApiFetch: (url: string, init?: { method?: string }) =>
    ((url.endsWith('/details') || url.endsWith('/submission')) && !init?.method) || url.startsWith('/api/files') ? sideApi(url, init) : api(url, init),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
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
  expect(JSON.parse(api.mock.calls[0][1].body)).toMatchObject({ task: 'Neue Aufgabe', todo_status_id: 2 });
  expect(api).toHaveBeenCalledOnce();
});
it('does not resend unchanged status, tags or assignees (keeps the completion date)', async () => {
  render(<TodoEditModal todo={{ ...todo, todo_status_id: 3, todo_status_code: 'done' }} canEdit participants={[]} tagSuggestions={[]} onSaved={saved} onClose={closed} onDeleted={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(JSON.parse(api.mock.calls[0][1].body)).toEqual({ task: 'Bankvollmacht einreichen' });
});
it('escape discards the draft instead of saving', () => {
  mount();
  fireEvent.change(screen.getByLabelText('Aufgabe'), { target: { value: 'Neue Aufgabe' } });
  fireEvent.keyDown(window, { key: 'Escape' });
  expect(closed).toHaveBeenCalledOnce();
  expect(api).not.toHaveBeenCalled();
});
it('explains a refused change of the own running fine', async () => {
  const { ApiError } = await import("@/lib/api/client");
  api.mockRejectedValue(new ApiError('x', 'conflict', 409, { code: 'todo_fine_running', message: 'x' }));
  mount();
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringContaining('Busse'), 'error'));
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
  expect(screen.queryByRole('button', { name: 'Pendenz löschen' })).not.toBeInTheDocument();
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
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(JSON.parse(api.mock.calls[0][1].body)).toMatchObject({ assigned_participant_ids: ['anna'] });
});
it('allows selecting and clearing multiple assignees', async () => {
  const people = [{ id: 'anna', display_name: 'Anna' }, { id: 'ben', display_name: 'Ben' }];
  render(<TodoEditModal todo={todo} canEdit participants={people as ParticipantSummary[]} tagSuggestions={[]} onSaved={saved} onClose={closed} onDeleted={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Zugewiesen an' }));
  for (const name of ['Anna', 'Ben', 'Anna']) fireEvent.click(screen.getByRole('option', { name: new RegExp(name) }));
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(JSON.parse(api.mock.calls[0][1].body).assigned_participant_ids).toEqual(['ben']);
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
  fireEvent.click(await screen.findByRole('option', { name: /Budget.xlsx/ }));
  expect(screen.getByRole('link', { name: /Budget.xlsx/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(api).toHaveBeenCalledTimes(2);
  expect(api.mock.calls[1][0]).toBe('/api/protocol-todos/todo-1/details');
  expect(JSON.parse(api.mock.calls[1][1].body)).toEqual({ file_ids: ['file-2'] });
});

describe('«Datei einsammeln» im Abschnitt Dateien', () => {
  const linked = { ...todo, submission_assignment_id: 'sa-1', element_ref: 'manual', reference_link: 'https://abgabe.example/tok/bankvollmacht/manual', resolved_due_date: '2026-11-30', assigned_participant_names: ['Anna Muster'] } as TodoListItem;
  const openStatus = { assignment_id: 'sa-1', title: 'Bankvollmacht einreichen', created_at: '2026-11-20T08:00:00Z', element_status: 'open', submitted_at: null, element_url: 'https://abgabe.example/tok/bankvollmacht/manual', files: [], can_stop: true };
  function withStatus(status: unknown) {
    sideApi.mockImplementation((url: string) => Promise.resolve(url.endsWith('/submission') ? status : url.startsWith('/api/files') ? files : { notes: '', files: [] }));
  }
  it('offers collecting only with the right and for a todo that is no submission yet', async () => {
    mount();
    expect(screen.queryByRole('button', { name: 'Einsammeln' })).not.toBeInTheDocument();
    cleanup();
    render(<TodoEditModal todo={{ ...todo, todo_status_code: 'done', todo_status_id: 3 }} canEdit canCollectSubmission participants={[]} tagSuggestions={[]} onSaved={saved} onClose={closed} onDeleted={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Einsammeln' })).not.toBeInTheDocument();
    cleanup();
    render(<TodoEditModal todo={todo} canEdit={false} canCollectSubmission participants={[]} tagSuggestions={[]} onSaved={saved} onClose={closed} onDeleted={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Einsammeln' })).not.toBeInTheDocument();
    cleanup();
    render(<TodoEditModal todo={todo} canEdit canCollectSubmission participants={[]} tagSuggestions={[]} onSaved={saved} onClose={closed} onDeleted={vi.fn()} />);
    expect(screen.getByText('Datei fehlt noch?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Einsammeln' })).toBeEnabled();
  });
  it('creates the submission with one click and switches to the status card', async () => {
    const updated = vi.fn();
    withStatus(openStatus);
    api.mockResolvedValueOnce({ assignment_id: 'sa-1', title: 'Bankvollmacht einreichen', public_slug: 'bankvollmacht-einreichen', element_url: linked.reference_link, todo: linked });
    render(<TodoEditModal todo={{ ...todo, assigned_participant_names: ['Anna Muster'] }} canEdit canCollectSubmission onUpdated={updated} participants={[]} tagSuggestions={[]} onSaved={saved} onClose={closed} onDeleted={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Einsammeln' }));
    await waitFor(() => expect(updated).toHaveBeenCalledOnce());
    expect(api).toHaveBeenCalledWith('/api/protocol-todos/todo-1/create-submission', { method: 'POST' });
    expect(updated.mock.calls[0][0]).toMatchObject({ id: 'todo-1', submission_assignment_id: 'sa-1' });
    expect(closed).not.toHaveBeenCalled();
    expect(await screen.findByText('Abgabe offen')).toBeInTheDocument();
    expect(screen.getByText('Einzelabgabe · Bankvollmacht einreichen')).toBeInTheDocument();
    expect(screen.getByLabelText('Link zur Abgabe')).toHaveValue(openStatus.element_url);
    expect(screen.getByText(/seit 20\.11\.2026 · noch keine Datei/)).toBeInTheDocument();
    expect(screen.getByText(/Anna Muster reicht ein, ohne Login/)).toBeInTheDocument();
    expect(screen.getByText('Wird automatisch erledigt, sobald die Datei eingereicht ist.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Öffnen/ })).toHaveAttribute('href', '/submission-assignments?assignment=sa-1');
    const [message, type] = toast.mock.calls[0];
    expect([message, type]).toEqual(['Abgabe «Bankvollmacht einreichen» erstellt', 'success']);
  });
  it('copies the link and stops collecting after confirmation', async () => {
    const updated = vi.fn();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    withStatus(openStatus);
    api.mockResolvedValueOnce({ ...todo, submission_assignment_id: null, reference_link: null });
    render(<TodoEditModal todo={linked} canEdit canCollectSubmission onUpdated={updated} participants={[]} tagSuggestions={[]} onSaved={saved} onClose={closed} onDeleted={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Link kopieren' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Kopiert ✓' })).toBeInTheDocument());
    expect(writeText).toHaveBeenCalledWith(openStatus.element_url);
    fireEvent.click(screen.getByRole('button', { name: 'Beenden' }));
    await waitFor(() => expect(updated).toHaveBeenCalledOnce());
    expect(api).toHaveBeenCalledWith('/api/protocol-todos/todo-1/stop-submission', { method: 'POST' });
    expect(updated.mock.calls[0][0]).toMatchObject({ submission_assignment_id: null });
    expect(await screen.findByText('Datei fehlt noch?')).toBeInTheDocument();
  });
  it('hides «Beenden» when the backend does not allow it', async () => {
    withStatus({ ...openStatus, can_stop: false });
    render(<TodoEditModal todo={linked} canEdit canCollectSubmission participants={[]} tagSuggestions={[]} onSaved={saved} onClose={closed} onDeleted={vi.fn()} />);
    expect(await screen.findByText('Abgabe offen')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Beenden' })).not.toBeInTheDocument();
  });
  it('lists the submitted file and shows the success banner once done', async () => {
    withStatus({ ...openStatus, element_status: 'submitted', submitted_at: '2026-11-18T20:14:00Z', can_stop: false,
      files: [{ id: 'f-9', original_name: 'Vollmacht-signiert.pdf', mime_type: 'application/pdf', file_size_bytes: 188416, content_url: '/api/submission-uploads/u-1/files/f-9/content', scan_status: 'clean' }] });
    render(<TodoEditModal todo={{ ...linked, todo_status_code: 'done', todo_status_id: 3 }} canEdit canReadSubmission participants={[]} tagSuggestions={[]} onSaved={saved} onClose={closed} onDeleted={vi.fn()} />);
    expect(await screen.findByText('Vollmacht-signiert.pdf')).toBeInTheDocument();
    expect(screen.getByText(/Eingereicht von Anna Muster/)).toBeInTheDocument();
    expect(screen.getByText('1 Datei')).toBeInTheDocument();
    expect(screen.getByText('Über die Abgabe eingereicht. Pendenz automatisch erledigt.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Erledigt' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByText('Abgabe offen')).not.toBeInTheDocument();
  });
  it('does not load the submission without the right to read it', async () => {
    withStatus(openStatus);
    render(<TodoEditModal todo={linked} canEdit participants={[]} tagSuggestions={[]} onSaved={saved} onClose={closed} onDeleted={vi.fn()} />);
    await waitFor(() => expect(sideApi).toHaveBeenCalled());
    expect(sideApi.mock.calls.some(([url]) => String(url).endsWith('/submission'))).toBe(false);
    expect(screen.queryByText('Abgabe offen')).not.toBeInTheDocument();
  });
  it('shows the backend reason as error toast', async () => {
    const { ApiError } = await import("@/lib/api/client");
    api.mockRejectedValueOnce(new ApiError('x', 'validation', 400, { code: 'todo_without_assignee', message: 'x' }));
    render(<TodoEditModal todo={todo} canEdit canCollectSubmission participants={[]} tagSuggestions={[]} onSaved={saved} onClose={closed} onDeleted={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Einsammeln' }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringContaining('verantwortliche Person'), 'error'));
  });
});
