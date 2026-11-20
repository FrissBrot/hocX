import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EventSummary, ParticipantSummary } from "@/types/api";

const apiFetch = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (...args: unknown[]) => apiFetch(...args) }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => showToast }));
// Rich-Text-Editor (TipTap) als einfaches Textfeld: hier zählt nur der Wert.
vi.mock("@/components/ui/rich-text-editor-lazy", () => ({
  LazyRichTextEditor: ({ value, onChange, readOnly }: { value: string; onChange: (v: string) => void; readOnly?: boolean }) => (
    <textarea data-testid="rte" value={value} readOnly={readOnly} onChange={(e) => onChange(e.target.value)} />
  ),
}));

import { blankEvent, clampParticipantCount, createEventBody, EVENT_PARTICIPANT_COUNT_MAX, EventDialog } from "./event-dialog";
import { EVENT_TEXT_SAVE_DELAY_MS } from "./use-event-autosave";
import { DEFAULT_EVENT_FIELD_CONFIG, publishEventFieldConfig } from "@/lib/hooks/use-event-field-config";

const participants = [
  { id: "p-1", display_name: "Anna Muster" },
  { id: "p-2", display_name: "Beat Beispiel" },
] as ParticipantSummary[];

function makeEvent(overrides: Partial<EventSummary> = {}): EventSummary {
  return { ...blankEvent("2026-05-02"), id: "e-1", tenant_id: "t-1", title: "Wanderung", ...overrides };
}

function renderDialog(props: Partial<Parameters<typeof EventDialog>[0]> = {}) {
  return render(
    <EventDialog
      open
      onClose={vi.fn()}
      event={null}
      availableParticipants={participants}
      knownEventTags={["Sitzung"]}
      cycleConfigs={[]}
      {...props}
    />
  );
}

beforeEach(() => {
  publishEventFieldConfig(DEFAULT_EVENT_FIELD_CONFIG);
  apiFetch.mockReset();
  apiFetch.mockImplementation(async (path: string) => (path === "/api/cycle-configs" ? [] : null));
  showToast.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("EventDialog – Anlegen", () => {
  it("erstellt erst mit Titel und Datum und reicht den neuen Termin weiter", async () => {
    const saved = makeEvent({ id: "e-new", title: "Lager" });
    apiFetch.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/api/events" && init?.method === "POST") return saved;
      return path === "/api/cycle-configs" ? [] : null;
    });
    const onCreated = vi.fn();
    renderDialog({ initialDate: "2026-05-02", onCreated });

    const create = screen.getByRole("button", { name: "Termin erstellen" });
    expect(create).toBeDisabled();
    expect(screen.getByRole("status").textContent).toContain("Titel und Datum ausfüllen");

    fireEvent.change(screen.getByLabelText("Titel"), { target: { value: "  Lager  " } });
    expect(create).toBeEnabled();
    fireEvent.click(create);

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(saved));
    const post = apiFetch.mock.calls.find(([path, init]) => path === "/api/events" && init?.method === "POST");
    const body = JSON.parse(post![1].body as string);
    expect(body).toMatchObject({ title: "Lager", event_date: "2026-05-02", event_end_date: null, participant_count: 0, is_cancelled: false });
    // Zyklen nicht angefasst: das Backend ordnet nach Datum zu.
    expect(body.cycle_assignments).toBeUndefined();
    expect(showToast).toHaveBeenCalledWith("Termin erstellt", "success");
  });

  it("bleibt ohne Datum gesperrt (Pflichtfeld)", () => {
    renderDialog({ initialDate: "" });
    fireEvent.change(screen.getByLabelText("Titel"), { target: { value: "Ohne Datum" } });
    expect(screen.getByRole("button", { name: "Termin erstellen" })).toBeDisabled();
  });

  it("zeigt einen Fehler-Toast, wenn das Anlegen scheitert", async () => {
    apiFetch.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/api/events" && init?.method === "POST") throw new Error("date must be between 1900-01-01 and 2999-12-31");
      return path === "/api/cycle-configs" ? [] : null;
    });
    const onCreated = vi.fn();
    renderDialog({ initialDate: "2026-05-02", onCreated });
    fireEvent.change(screen.getByLabelText("Titel"), { target: { value: "Lager" } });
    fireEvent.click(screen.getByRole("button", { name: "Termin erstellen" }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("date must be between 1900-01-01 and 2999-12-31", "error"));
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("Anlegen und Bearbeiten zeigen dieselben Reiter", () => {
    const { unmount } = renderDialog({ initialDate: "2026-05-02" });
    const createTabs = screen.getAllByRole("tab").map((tab) => tab.textContent);
    unmount();
    renderDialog({ event: makeEvent(), onUpdate: vi.fn() });
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(createTabs);
    expect(createTabs).toEqual(["Übersicht", "Teilnehmer & Status", "Weitere Felder"]);
  });
});

describe("EventDialog – Bearbeiten", () => {
  it("speichert den Titel automatisch nach der Tipp-Pause", async () => {
    vi.useFakeTimers();
    const onUpdate = vi.fn().mockResolvedValue(true);
    renderDialog({ event: makeEvent(), onUpdate });
    expect(screen.queryByRole("button", { name: "Termin erstellen" })).toBeNull();

    fireEvent.change(screen.getByLabelText("Titel"), { target: { value: "Wanderung Rigi" } });
    expect(onUpdate).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(EVENT_TEXT_SAVE_DELAY_MS);
      await vi.runAllTimersAsync();
    });
    expect(onUpdate).toHaveBeenCalledWith({ title: "Wanderung Rigi" });
    expect(screen.getByRole("status").textContent).toBe("Alle Änderungen gespeichert");
  });

  it("meldet «Nicht gespeichert», wenn das Speichern scheitert", async () => {
    const onUpdate = vi.fn().mockResolvedValue(false);
    renderDialog({ event: makeEvent(), onUpdate });
    fireEvent.click(screen.getByRole("tab", { name: /Teilnehmer & Status/ }));
    await act(async () => {
      fireEvent.click(screen.getByRole("checkbox", { name: /Termin abgesagt/ }));
    });
    expect(onUpdate).toHaveBeenCalledWith({ is_cancelled: true });
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Nicht gespeichert"));
  });

  it("wählt Personen einer Rolle mit Ausgangsstand für den Server", async () => {
    const onUpdate = vi.fn().mockResolvedValue(true);
    renderDialog({ event: makeEvent({ organizer_ids: ["p-2"] }), onUpdate });
    fireEvent.click(screen.getByRole("tab", { name: /Teilnehmer & Status/ }));
    expect(screen.getByText("Beat Beispiel")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Bearbeiten" })[0]);
    expect(screen.getByText("Organisatoren wählen")).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("checkbox", { name: "Anna Muster" }));
    });
    expect(onUpdate).toHaveBeenCalledWith({ organizer_ids: ["p-2", "p-1"], role_ids_base: { organizer_ids: ["p-2"] } });
  });

  it("zeigt im Menü Löschen und Absage", async () => {
    const onDelete = vi.fn();
    const onUpdate = vi.fn().mockResolvedValue(true);
    renderDialog({ event: makeEvent(), onUpdate, onDelete });
    fireEvent.click(screen.getByRole("button", { name: "Mehr: Löschen, Abgesagt markieren" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Löschen" }));
    expect(onDelete).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Mehr: Löschen, Abgesagt markieren" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: "Als abgesagt markieren" }));
    });
    expect(onUpdate).toHaveBeenCalledWith({ is_cancelled: true });
  });

  it("ohne Recht: Hinweis, Felder gesperrt, kein Menü", () => {
    renderDialog({ event: makeEvent(), onUpdate: vi.fn(), readOnly: true });
    expect(screen.getByText(/Nur Ansicht/)).toBeInTheDocument();
    expect(screen.getByLabelText("Titel")).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "Mehr: Löschen, Abgesagt markieren" })).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("EventDialog – Zusatzfelder (event_field_config)", () => {
  it("übernimmt Namen und blendet ausgeblendete Spezialfelder aus", () => {
    publishEventFieldConfig({
      ...DEFAULT_EVENT_FIELD_CONFIG,
      spezial_text1: { label: "Material", hidden: false },
      spezial_text2: { label: "", hidden: true },
      spezial_text3: { label: "", hidden: true },
      spezial_time1: { label: "Treffpunkt-Zeit", hidden: false },
      spezial_time2: { label: "", hidden: true },
      spezial2_ids: { label: "", hidden: true },
      spezial1_ids: { label: "Fahrer", hidden: false },
    });
    renderDialog({ event: makeEvent(), onUpdate: vi.fn(), fieldSettingsHref: "/tenant-settings" });

    fireEvent.click(screen.getByRole("tab", { name: /Weitere Felder/ }));
    expect(screen.getByText("Material")).toBeInTheDocument();
    expect(screen.getByText("Treffpunkt-Zeit")).toBeInTheDocument();
    expect(screen.queryByText("Spezial Text 2")).toBeNull();
    expect(screen.getByRole("link", { name: "Zu den Einstellungen" })).toHaveAttribute("href", "/tenant-settings#event-fields");

    fireEvent.click(screen.getByRole("tab", { name: /Teilnehmer & Status/ }));
    expect(screen.getByText("Fahrer")).toBeInTheDocument();
    expect(screen.queryByText("Spezial 2")).toBeNull();
    expect(screen.getByText("Spezial 3")).toBeInTheDocument();
  });
});

describe("Hilfsfunktionen", () => {
  it("begrenzt die Teilnehmerzahl auf den Spaltenbereich", () => {
    expect(clampParticipantCount(-3)).toBe(0);
    expect(clampParticipantCount(12.7)).toBe(12);
    expect(clampParticipantCount(Number.NaN)).toBe(0);
    expect(clampParticipantCount(1e12)).toBe(EVENT_PARTICIPANT_COUNT_MAX);
  });

  it("schickt ein Enddatum nur, wenn es nach dem Start liegt", () => {
    const draft = { ...blankEvent("2026-05-02"), title: " Lager ", event_end_date: "2026-05-01" };
    expect(createEventBody(draft, undefined).event_end_date).toBeNull();
    expect(createEventBody({ ...draft, event_end_date: "2026-05-04" }, undefined).event_end_date).toBe("2026-05-04");
    expect(createEventBody(draft, undefined).title).toBe("Lager");
  });
});
