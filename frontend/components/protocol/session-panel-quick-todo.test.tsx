import { createRef, forwardRef, useState, type ComponentProps } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ParticipantSummary, ProtocolSummary } from "@/types/api";

const apiFetch = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, browserApiFetch: (...args: unknown[]) => apiFetch(...args) };
});
vi.mock("@/contexts/toast-context", () => ({ useToast: () => showToast }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { SessionPanel, type ActivePanel, type SessionPanelHandle } from "./session-panel";

type HarnessProps = Omit<ComponentProps<typeof SessionPanel>, "active" | "onClose" | "ref"> & { initial?: ActivePanel };

// Die Schublade des Editors steuert, welcher Teil sichtbar ist (protocol-dock.tsx); hier nachgebildet
const Harness = forwardRef<SessionPanelHandle, HarnessProps>(function Harness({ initial = "todo", ...props }, ref) {
  const [active, setActive] = useState<ActivePanel>(initial);
  return <SessionPanel ref={ref} {...props} active={active} onClose={() => setActive(null)} />;
});

const todoOpen = (container: HTMLElement) => !container.querySelector(".session-panel-todo-wrap")?.hasAttribute("hidden");

// «Schnelle Pendenz» im Sitzungsmodus: Karte «Datei als Abgabe einsammeln», Tastatur (Leertaste,
// Alt+A, Enter, Escape), Menü bleibt nach dem Erstellen offen und leer, Abgabe nach der Pendenz.

const protocol = { id: "p-1", session_notes: "" } as unknown as ProtocolSummary;
const anna = { id: "pa-1", display_name: "Anna Muster", first_name: "Anna", last_name: "Muster", joined_at: null, left_at: null } as ParticipantSummary;
const beat = { id: "pa-2", display_name: "Beat Bär", first_name: "Beat", last_name: "Bär", joined_at: null, left_at: null } as ParticipantSummary;

function setup(props: { canCollectSubmissions?: boolean } = {}) {
  const ref = createRef<SessionPanelHandle>();
  const onQuickTodoCreated = vi.fn();
  const utils = render(
    <Harness ref={ref} protocol={protocol} participants={[anna, beat]} onQuickTodoCreated={onQuickTodoCreated} canCollectSubmissions={props.canCollectSubmissions ?? true} />
  );
  const task = screen.getByRole("textbox", { name: "Aufgabe" });
  const person = screen.getByRole("combobox", { name: "Person" });
  return { ...utils, ref, task, person, onQuickTodoCreated };
}

function pickPerson(person: HTMLElement, text: string) {
  fireEvent.change(person, { target: { value: text } });
  fireEvent.keyDown(person, { key: "Enter" });
}

beforeEach(() => {
  apiFetch.mockReset();
  showToast.mockReset();
  apiFetch.mockImplementation(async (path: string) => {
    if (path.endsWith("/quick-todos")) return { block_id: "b-1", todo_id: "t-1", element_id: "e-1" };
    if (path.endsWith("/create-submission")) return { assignment_id: "sa-1", title: "Abgabe", public_slug: "x", element_url: null, todo: {} };
    return {};
  });
});

describe("Schnelle Pendenz", () => {
  it("shows the collect card only when allowed and toggles it with click, Space-click and Alt+A", () => {
    const { unmount } = setup({ canCollectSubmissions: false });
    expect(screen.queryByRole("checkbox", { name: /Datei als Abgabe einsammeln/ })).toBeNull();
    expect(screen.getByText("Enter erstellt · Esc erstellt und schliesst")).toBeTruthy();
    unmount();

    const { task } = setup();
    const card = screen.getByRole("checkbox", { name: /Datei als Abgabe einsammeln/ });
    expect(card.getAttribute("aria-checked")).toBe("false");
    expect(screen.getByText("Enter erstellt · Alt+A Abgabe · Esc erstellt und schliesst")).toBeTruthy();
    fireEvent.click(card);
    expect(card.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("button", { name: "Pendenz + Abgabe erstellen" })).toBeTruthy();
    expect(screen.getByText("Die Person reicht ohne Login ein, dann ist die Pendenz erledigt.")).toBeTruthy();
    // Alt+A über event.code (Mac ⌥A liefert «å»)
    fireEvent.keyDown(task, { key: "å", code: "KeyA", altKey: true });
    expect(card.getAttribute("aria-checked")).toBe("false");
    fireEvent.keyDown(task, { key: "a", code: "KeyA", altKey: true });
    expect(card.getAttribute("aria-checked")).toBe("true");
    // Strg+Alt (AltGr unter Windows) ist kein Shortcut
    fireEvent.keyDown(task, { key: "a", code: "KeyA", altKey: true, ctrlKey: true });
    expect(card.getAttribute("aria-checked")).toBe("true");
  });

  it("shows profile badges in the person options and the chosen value, and names the person in the hint", () => {
    const { person } = setup();
    fireEvent.change(person, { target: { value: "b" } });
    const options = screen.getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual(["BBBeat Bär"]);
    expect(options[0].querySelector(".participant-avatar")?.textContent).toBe("BB");
    fireEvent.keyDown(person, { key: "Enter" });
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(person.parentElement?.querySelector(".quick-todo-field-avatar")?.textContent).toBe("BB");
    fireEvent.click(screen.getByRole("checkbox", { name: /Datei als Abgabe einsammeln/ }));
    expect(screen.getByText("Beat reicht ohne Login ein, dann ist die Pendenz erledigt.")).toBeTruthy();
  });

  it("Enter on the person field picks the option instead of creating; Enter in the title creates and keeps the menu open and empty", async () => {
    const { task, person, onQuickTodoCreated, container } = setup();
    fireEvent.change(task, { target: { value: "Mittag reservieren" } });
    pickPerson(person, "ann");
    expect(apiFetch).not.toHaveBeenCalled();
    expect((person as HTMLInputElement).value).toBe("Anna Muster");

    fireEvent.keyDown(task, { key: "Enter" });
    await waitFor(() => expect(onQuickTodoCreated).toHaveBeenCalledWith("b-1", "t-1", "e-1"));
    expect(apiFetch).toHaveBeenCalledWith("/api/protocol-todos/t-1", { method: "PATCH", body: JSON.stringify({ assigned_participant_id: "pa-1" }) });
    expect(apiFetch.mock.calls.some(([path]) => String(path).includes("create-submission"))).toBe(false);
    expect(screen.getByRole("status").textContent).toBe("✓ Erstellt: Mittag reservieren");
    expect((task as HTMLInputElement).value).toBe("");
    expect((person as HTMLInputElement).value).toBe("");
    expect(document.activeElement).toBe(task);
    expect(todoOpen(container)).toBe(true);
  });

  it("creates the submission after the todo when the card is checked (Enter on the card creates)", async () => {
    const { task, person, onQuickTodoCreated } = setup();
    fireEvent.change(task, { target: { value: "Bericht" } });
    pickPerson(person, "anna");
    const card = screen.getByRole("checkbox", { name: /Datei als Abgabe einsammeln/ });
    fireEvent.click(card);
    fireEvent.keyDown(card, { key: "Enter" });
    await waitFor(() => expect(onQuickTodoCreated).toHaveBeenCalled());
    const paths = apiFetch.mock.calls.map(([path]) => path);
    expect(paths).toEqual(["/api/protocols/p-1/quick-todos", "/api/protocol-todos/t-1", "/api/protocol-todos/t-1/create-submission"]);
    expect(screen.getByRole("status").textContent).toBe("✓ Erstellt: Bericht · mit Abgabe");
    expect(card.getAttribute("aria-checked")).toBe("false");
  });

  it("refuses collecting without a person: error text, red person field, focus there, nothing created", () => {
    const { task, person } = setup();
    fireEvent.change(task, { target: { value: "Bericht" } });
    fireEvent.keyDown(task, { key: "a", code: "KeyA", altKey: true });
    expect(person.getAttribute("aria-invalid")).toBe("true");
    fireEvent.keyDown(task, { key: "Enter" });
    expect(screen.getByText("Zuerst eine Person zuweisen.")).toBeTruthy();
    expect(document.activeElement).toBe(person);
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("keeps the todo when creating the submission fails and reports the backend message", async () => {
    apiFetch.mockImplementation(async (path: string) => {
      if (path.endsWith("/quick-todos")) return { block_id: "b-1", todo_id: "t-1", element_id: "e-1" };
      if (path.endsWith("/create-submission")) throw new Error("Kein Standard-Link");
      return {};
    });
    const { task, person, onQuickTodoCreated } = setup();
    fireEvent.change(task, { target: { value: "Bericht" } });
    pickPerson(person, "anna");
    fireEvent.click(screen.getByRole("checkbox", { name: /Datei als Abgabe einsammeln/ }));
    fireEvent.click(screen.getByRole("button", { name: "Pendenz + Abgabe erstellen" }));
    await waitFor(() => expect(onQuickTodoCreated).toHaveBeenCalledWith("b-1", "t-1", "e-1"));
    expect(showToast).toHaveBeenCalledWith("Kein Standard-Link", "error");
    expect(screen.getByRole("status").textContent).toBe("✓ Erstellt: Bericht");
  });

  it("Escape creates the todo (with submission) and closes; without a title it only closes", async () => {
    const { task, person, onQuickTodoCreated, container } = setup();
    const isOpen = () => todoOpen(container);
    fireEvent.change(task, { target: { value: "Per Escape" } });
    pickPerson(person, "anna");
    fireEvent.keyDown(task, { key: "a", code: "KeyA", altKey: true });
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(onQuickTodoCreated).toHaveBeenCalledWith("b-1", "t-1", "e-1"));
    expect(apiFetch.mock.calls.map(([path]) => path)).toContain("/api/protocol-todos/t-1/create-submission");
    await waitFor(() => expect(isOpen()).toBe(false));
  });

  it("Escape with collect checked but no person shows the error and keeps the menu open", async () => {
    const { task, container } = setup();
    fireEvent.change(task, { target: { value: "Ohne Person" } });
    fireEvent.keyDown(task, { key: "a", code: "KeyA", altKey: true });
    fireEvent.keyDown(window, { key: "Escape" });
    await act(async () => {});
    expect(screen.getByText("Zuerst eine Person zuweisen.")).toBeTruthy();
    expect(apiFetch).not.toHaveBeenCalled();
    expect(todoOpen(container)).toBe(true);
  });

  it("Escape without a title only closes", async () => {
    const { container } = setup();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(todoOpen(container)).toBe(false));
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("sets the tag from «Zu Punkt»", () => {
    render(<Harness protocol={protocol} participants={[anna]} sections={[{ id: "e-1", name: "Kasse" }, { id: "e-2", name: "Varia" }]} currentSectionName="Kasse" />);
    const select = screen.getByRole("combobox", { name: "Zu Punkt" }) as HTMLSelectElement;
    expect(select.value).toBe("Kasse");
    fireEvent.change(select, { target: { value: "Varia" } });
    expect((screen.getByRole("textbox", { name: "Kategorie / Tag" }) as HTMLInputElement).value).toBe("Varia");
  });

  it("offers smart dates in the due field and saves the picked date", async () => {
    const { task, onQuickTodoCreated } = setup();
    const due = screen.getByRole("combobox", { name: "Fällig" });
    fireEvent.focus(due);
    const labels = screen.getAllByRole("option").map((option) => option.querySelector(".session-panel-option-name")?.textContent);
    expect(labels.slice(0, 3)).toEqual(["Morgen", "Übermorgen", expect.any(String)]);
    expect(labels).toContain("Ende Monat");
    expect(labels.slice(-2)).toEqual(["Nächster Hock", "Kein Enddatum"]);
    // Tippen filtert wie im Fälligkeitsmenü, auch ohne Umlaut
    fireEvent.change(due, { target: { value: "uberm" } });
    const typed = screen.getAllByRole("option").map((option) => option.querySelector(".session-panel-option-name")?.textContent);
    expect(typed[0]).toBe("Übermorgen");
    fireEvent.keyDown(due, { key: "Enter" });
    expect((due as HTMLInputElement).value).toMatch(/^Übermorgen \(\d{2}\.\d{2}\.\d{4}\)$/);

    const today = new Date();
    const expected = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 2);
    const iso = `${expected.getFullYear()}-${String(expected.getMonth() + 1).padStart(2, "0")}-${String(expected.getDate()).padStart(2, "0")}`;
    fireEvent.change(task, { target: { value: "Mit Frist" } });
    fireEvent.keyDown(task, { key: "Enter" });
    await waitFor(() => expect(onQuickTodoCreated).toHaveBeenCalled());
    expect(apiFetch).toHaveBeenCalledWith("/api/protocol-todos/t-1", { method: "PATCH", body: JSON.stringify({ due_date: iso, due_event_id: null, due_marker: null }) });
  });

  it("prefills the title with text selected in a protocol field", () => {
    const ref = createRef<SessionPanelHandle>();
    render(
      <>
        <textarea aria-label="Feld" defaultValue="Bitte Mittag reservieren für Skiweekend" />
        <Harness ref={ref} protocol={protocol} participants={[anna]} initial={null} />
      </>
    );
    const field = screen.getByRole("textbox", { name: "Feld" }) as HTMLTextAreaElement;
    field.focus();
    field.setSelectionRange(6, 39);
    act(() => ref.current?.prefillTodoFromSelection());
    expect((screen.getByRole("textbox", { name: "Aufgabe" }) as HTMLInputElement).value).toBe("Mittag reservieren für Skiweekend");
  });
});
