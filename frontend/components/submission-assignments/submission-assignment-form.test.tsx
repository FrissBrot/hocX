import { fireEvent, render, screen, within } from "@testing-library/react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  FormState,
  ResponsibleCandidate,
  SubmissionAssignmentFormModal,
  assignmentPayload,
  describeAssignment,
  formFromAssignment,
  newManualElement,
  formProblem,
  OFFSET_DAYS_MAX,
  initialForm,
  assignmentTemplates,
  pickExampleEvent,
  publicUrlParts,
  sectionSummaries,
  slugify,
  windowExample,
} from "./submission-assignment-form";
import { assignmentPublicUrl } from "./submission-share-link";
import { SubmissionAssignment, SubmissionLink } from "@/types/api";

const t = useTranslations("submissionAssignments");

const link = (overrides: Partial<SubmissionLink> = {}): SubmissionLink => ({
  id: "link-1",
  name: "Standard",
  is_default: true,
  token: "tok",
  url: "https://abgabe.hocx.ch/verein-alpina",
  assignment_count: 0,
  created_at: "2026-09-19T10:00:00Z",
  ...overrides,
});

const people: ResponsibleCandidate[] = [
  { id: "p-anna", display_name: "Anna Muster", is_active: true },
  { id: "p-ben", display_name: "Ben Beispiel", is_active: true },
  { id: "p-alt", display_name: "Ehemalig", is_active: false },
];

function Harness({
  start = initialForm,
  onSubmit = vi.fn(),
  editing = false,
  onChange,
  confirmRemoveElement,
}: {
  start?: FormState;
  onSubmit?: () => void;
  editing?: boolean;
  onChange?: (form: FormState) => void;
  confirmRemoveElement?: (name: string) => Promise<boolean>;
}) {
  const [form, setFormState] = useState<FormState>(start);
  const setForm: typeof setFormState = (update) =>
    setFormState((current) => {
      const next = typeof update === "function" ? update(current) : update;
      onChange?.(next);
      return next;
    });
  return (
    <SubmissionAssignmentFormModal
      open
      editing={editing}
      tenantName="Verein Alpina"
      form={form}
      setForm={setForm}
      links={[link(), link({ id: "link-2", name: "Vorstand intern", is_default: false })]}
      availableLists={[]}
      availableTags={["Scharanlass", "Hauptversammlung"]}
      availableCycleConfigs={[]}
      availableParticipants={people}
      confirmRemoveElement={confirmRemoveElement}
      onSubmit={onSubmit}
      onClose={vi.fn()}
      onManageLinks={vi.fn()}
    />
  );
}

describe("describeAssignment – automatisch schliessen", () => {
  const base: FormState = { ...initialForm, title: "Bericht", source_type: "manual", manual_elements: [newManualElement("Bericht")] };

  it("erwähnt nichts, wenn nie automatisch geschlossen wird", () => {
    expect(describeAssignment(base, null, t)).not.toContain("automatisch");
  });

  it("beschreibt das Schliessen nach der ersten Abgabe bzw. beim Maximum", () => {
    expect(describeAssignment({ ...base, auto_close: "first_upload" }, null, t)).toContain("nach der ersten Abgabe");
    expect(describeAssignment({ ...base, auto_close: "max_files", max_files_per_element: 1 }, null, t)).toContain("sobald 1 Datei abgegeben wurde");
  });
});

describe("Automatisch schliessen im Formular", () => {
  it("deaktiviert «Maximum» ohne Maximum und fällt beim Leeren auf «Nie» zurück", () => {
    render(<Harness start={{ ...initialForm, auto_close: "max_files", max_files_per_element: 3 }} />);
    fireEvent.click(screen.getByRole("button", { name: /4\. Dateien/ }));
    const maxOption = screen.getByRole("radio", { name: "Sobald Höchstzahl erreicht" });
    expect(maxOption.getAttribute("aria-checked")).toBe("true");

    fireEvent.change(screen.getByPlaceholderText("unbegrenzt"), { target: { value: "" } });

    expect(maxOption).toHaveProperty("disabled", true);
    expect(screen.getByRole("radio", { name: "Nie" }).getAttribute("aria-checked")).toBe("true");
  });
});

describe("formProblem", () => {
  it("verlangt Titel und für Termine einen Tag", () => {
    expect(formProblem(initialForm, t)).toBe("Titel fehlt");
    expect(formProblem({ ...initialForm, title: "Bilder" }, t)).toBe("Tag-Filter fehlt");
    expect(formProblem({ ...initialForm, title: "Bilder", tag_filter: "Scharanlass" }, t)).toBeNull();
  });

  it("verlangt für Listen eine Liste, für Einzelabgaben benannte Elemente mit gültigem Zeitfenster", () => {
    expect(formProblem({ ...initialForm, title: "Bilder", source_type: "list" }, t)).toBe("Liste fehlt");
    const manual: FormState = { ...initialForm, title: "Bilder", source_type: "manual" };
    expect(formProblem(manual, t)).toBe("Mindestens ein Element anlegen");
    expect(formProblem({ ...manual, manual_elements: [newManualElement("Bilder")] }, t)).toBeNull();
    expect(formProblem({ ...manual, manual_elements: [newManualElement("Bilder"), newManualElement("  ")] }, t)).toBe("Jedes Element braucht einen Namen");
    const backwards = newManualElement("Bilder", { window_start: "2026-12-10", window_end: "2026-12-01" });
    expect(formProblem({ ...manual, manual_elements: [backwards] }, t)).toBe("Bei einem Element liegt der Start nach dem Stichtag");
  });

  it("begrenzt das Zeitfenster auf OFFSET_DAYS_MAX Tage", () => {
    const form = { ...initialForm, title: "Bilder", tag_filter: "x" };
    expect(formProblem({ ...form, offset_days_before: OFFSET_DAYS_MAX, offset_days_after: 0 }, t)).toBeNull();
    expect(formProblem({ ...form, offset_days_after: OFFSET_DAYS_MAX + 1 }, t)).toMatch(/3650/);
    expect(formProblem({ ...form, offset_days_before: 1_000_000_000 }, t)).toMatch(/3650/);
  });

  it("verlangt bei aktivem Zyklus-Filter mindestens einen Zyklus", () => {
    const form = { ...initialForm, title: "Bilder", tag_filter: "x", cycle_config_id: "cfg", cycle_offsets: [] };
    expect(formProblem(form, t)).toMatch(/Zyklus/);
  });
});

describe("describeAssignment", () => {
  it("beschreibt das Zeitfenster einer Termin-Abgabe", () => {
    const form = { ...initialForm, tag_filter: "Scharanlass", offset_days_before: 7, offset_days_after: 3 };
    expect(describeAssignment(form, null, t)).toBe(
      "Jeder Termin mit dem Tag «Scharanlass» bekommt ein eigenes Abgabefeld. Es öffnet 7 Tage vor dem Termin und schliesst 3 Tage danach.",
    );
  });

  it("beschreibt Termin-Abgaben ohne Zeitfenster als offen bis zum manuellen Schliessen", () => {
    expect(describeAssignment({ ...initialForm, tag_filter: "x" }, null, t)).toContain("bleibt offen, bis es von Hand geschlossen wird");
  });

  it("beschreibt Einzelabgaben mit ihren Elementen, dem nächsten Stichtag und den Pendenzen", () => {
    const manual: FormState = { ...initialForm, source_type: "manual", manual_elements: [newManualElement("Anmeldung")] };
    expect(describeAssignment(manual, null, t)).toContain("ein Abgabeelement");
    expect(describeAssignment(manual, null, t)).toContain("bleibt ein Element offen");
    const two: FormState = {
      ...manual,
      manual_elements: [
        newManualElement("Anmeldung", { window_end: "2026-12-31", responsible_participant_ids: ["p-anna"] }),
        newManualElement("Fotos", { window_end: "2026-12-20" }),
      ],
    };
    expect(describeAssignment(two, null, t)).toContain("2 Abgabeelemente");
    expect(describeAssignment(two, null, t)).toContain("am 20.12.2026");
    expect(describeAssignment(two, null, t)).toContain("Für ein Element entsteht eine Pendenz.");
  });

  it("nennt bei Listen den Namen der Liste", () => {
    expect(describeAssignment({ ...initialForm, source_type: "list" }, "Vorstand", t)).toContain("«Vorstand»");
  });
});

describe("publicUrlParts / slugify", () => {
  it("zeigt die Adresse ohne Protokoll und den Slug separat", () => {
    expect(publicUrlParts(link(), "bilder-scharanlass")).toEqual({ base: "abgabe.hocx.ch/verein-alpina/", slug: "bilder-scharanlass" });
    expect(publicUrlParts(null, "x")).toBeNull();
  });

  it("wandelt Umlaute im Slug um", () => {
    expect(slugify("Bilder Schäranlass!")).toBe("bilder-schaeranlass");
  });
});

const goTo = (name: RegExp) => fireEvent.click(screen.getByRole("button", { name }));

describe("SubmissionAssignmentFormModal – Anlegen in fünf Schritten", () => {
  it("führt durch Grundlage, Zeitraum, Verantwortlich, Dateien und Zugriff", () => {
    render(<Harness />);
    expect(screen.getByText("Schritt 1 von 5")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Was soll abgegeben werden?" })).toBeInTheDocument();
    const radios = within(screen.getByRole("radiogroup", { name: "Wofür wird einzeln abgegeben?" })).getAllByRole("radio");
    expect(radios.map((r) => r.textContent)).toEqual([
      expect.stringContaining("Termine"),
      expect.stringContaining("Liste"),
      expect.stringContaining("Einzelabgabe"),
    ]);
    expect(radios[0]).toHaveAttribute("aria-checked", "true");

    fireEvent.click(screen.getByRole("button", { name: "Weiter" }));
    expect(screen.getByRole("heading", { name: "Wann ist die Abgabe offen?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zurück" }));
    expect(screen.getByText("Schritt 1 von 5")).toBeInTheDocument();
    // Ohne Erstellen-Knopf vor dem letzten Schritt
    expect(screen.queryByRole("button", { name: "Abgabe erstellen" })).not.toBeInTheDocument();
  });

  it("wählt den Tag als Chip und erlaubt bei «Einzelabgabe» das Erstellen ohne Tag", () => {
    const onSubmit = vi.fn();
    render(<Harness start={{ ...initialForm, title: "Vereinsfotos", public_slug: "vereinsfotos" }} onSubmit={onSubmit} />);
    expect(screen.getByRole("radiogroup", { name: "Tag-Filter" })).toBeInTheDocument();

    goTo(/5\. Zugriff/);
    const submit = screen.getByRole("button", { name: "Abgabe erstellen" });
    expect(submit).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Noch offen: Tag-Filter fehlt");

    goTo(/1\. Grundlage/);
    fireEvent.click(screen.getByRole("radio", { name: /Einzelabgabe/ }));
    expect(screen.queryByText("Tag-Filter")).not.toBeInTheDocument();

    // Schritt 2 heisst bei Einzelabgaben «Elemente»; das erste Element trägt den Titel
    goTo(/2\. Elemente/);
    expect(screen.getByRole("heading", { name: "Welche Elemente sollen abgegeben werden?" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("Vereinsfotos")).toBeInTheDocument();
    goTo(/4\. Dateien/);
    expect(screen.queryByText("Sortierung")).not.toBeInTheDocument();

    goTo(/5\. Zugriff/);
    expect(screen.getByRole("button", { name: "Abgabe erstellen" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Abgabe erstellen" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("zeigt Eyebrow und im Schritt Zugriff die Adresse mit Slug und den Standard-Link", () => {
    render(<Harness start={{ ...initialForm, title: "Bilder", public_slug: "bilder", link_ids: ["link-1"] }} />);
    expect(screen.getAllByText("Neue Abgabe").length).toBeGreaterThan(0);
    expect(screen.getByText("Verein Alpina")).toBeInTheDocument();
    goTo(/5\. Zugriff/);
    expect(screen.getByText("bilder").tagName).toBe("STRONG");
    expect(screen.getByText("Standard", { selector: "small" })).toBeInTheDocument();
  });

  it("übernimmt den Titel in die Überschrift", () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText("Titel"), { target: { value: "Bilder Scharanlass" } });
    expect(screen.getByLabelText("Titel")).toHaveValue("Bilder Scharanlass");
    expect(screen.getByRole("heading", { name: "Bilder Scharanlass" })).toBeInTheDocument();
  });

  it("zählt gewählte Dateitypen und wechselt zwischen «Alle» und «Keine»", () => {
    render(<Harness />);
    goTo(/4\. Dateien/);
    expect(screen.getByText("alle erlaubt")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Alle" })[0]);
    expect(screen.getByText("1 ausgewählt")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keine" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: ".png" }));
    expect(screen.getByText("2 ausgewählt")).toBeInTheDocument();
  });
});

describe("SubmissionAssignmentFormModal – Bearbeiten als Karten", () => {
  it("zeigt je Abschnitt eine Zusammenfassung und öffnet jeweils eine Karte", () => {
    render(<Harness editing start={{ ...initialForm, title: "Berichte", tag_filter: "Scharanlass", offset_days_before: 0, offset_days_after: 7, link_ids: ["link-1"] }} />);
    expect(screen.queryByText(/Schritt 1 von 5/)).not.toBeInTheDocument();
    expect(screen.getByText("Termine mit Tag «Scharanlass»")).toBeInTheDocument();
    expect(screen.getByText("ab 0 Tagen vorher, bis 7 Tage danach")).toBeInTheDocument();

    const toggles = screen.getAllByRole("button", { name: /Ändern/ });
    expect(toggles).toHaveLength(5);
    fireEvent.click(toggles[3]);
    expect(screen.getByText("Erlaubte Dateitypen")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Fertig/ })).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(screen.getAllByRole("button", { name: /Ändern/ })[0]);
    expect(screen.queryByText("Erlaubte Dateitypen")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Abgabe speichern" })).toBeEnabled();
  });
});

describe("sectionSummaries", () => {
  const context = { listName: null, cycleName: null, responsibleLabel: null, hasResponsibleOptions: true, linkNames: [] as string[] };

  it("warnt, wenn Tag oder Link fehlen", () => {
    const summary = sectionSummaries({ ...initialForm, title: "X" }, context, t);
    expect(summary.basics).toMatchObject({ value: "Termine – Tag fehlt", warn: true });
    expect(summary.access).toMatchObject({ detail: "Ohne Link ist die Abgabe nicht erreichbar", warn: true });
  });

  it("fasst Verantwortliche, Dateien und Zugriff zusammen", () => {
    const form: FormState = { ...initialForm, title: "X", tag_filter: "Höck", responsible_participant_source: "spezial1_ids", reviewer_ids: ["r1"], allowed_file_types: ["pdf"], max_files_per_element: 3, link_ids: ["l1"] };
    const summary = sectionSummaries(form, { ...context, responsibleLabel: "Spezial 1", linkNames: ["Eltern"] }, t);
    expect(summary.responsible.value).toBe("Spezial 1 · Link: verwalten");
    expect(summary.responsible.detail).toBe("Pendenz je Termin · persönlicher Link 30 Tage gültig");
    expect(summary.files.value).toBe("1 Dateityp · max. 3 Dateien · max. 20 MB");
    expect(summary.access).toMatchObject({ value: "Eltern · 1 Prüfer", detail: "Dateien sehen: Standard der Organisation", warn: false });
  });

  it("fasst bei Einzelabgaben Elemente, nächsten Stichtag und Verantwortliche zusammen", () => {
    const form: FormState = {
      ...initialForm,
      title: "X",
      source_type: "manual",
      manual_elements: [
        newManualElement("Anmeldung", { window_end: "2026-11-30", responsible_participant_ids: ["p-anna"] }),
        newManualElement("Fotos"),
      ],
    };
    const summary = sectionSummaries(form, { ...context, hasResponsibleOptions: false }, t);
    expect(summary.window).toMatchObject({ label: "Abgabeelemente", value: "2 Elemente", detail: "Anmeldung, Fotos · nächster Stichtag 30.11.2026", warn: false });
    expect(summary.responsible).toMatchObject({ value: "1 Element mit Verantwortlichen · Link: verwalten", detail: "Pendenz je Element · persönlicher Link 30 Tage gültig" });
    const nobody = sectionSummaries({ ...form, manual_elements: [newManualElement("Anmeldung")] }, context, t);
    expect(nobody.responsible.value).toBe("Keine Zuweisung");
  });
});

describe("Einzelabgabe mit mehreren Elementen (Migration 0198)", () => {
  const manualStart: FormState = { ...initialForm, title: "Lager", public_slug: "lager", source_type: "manual", manual_elements: [newManualElement("Anmeldung")] };

  it("legt Elemente mit «+ Element» an, entfernt sie per Icon und sendet sie mit Verantwortlichen", () => {
    let latest: FormState = manualStart;
    render(<Harness start={manualStart} onChange={(form) => (latest = form)} />);
    goTo(/2\. Elemente/);
    // Das letzte Element lässt sich nicht entfernen
    expect(screen.getByRole("button", { name: "Element «Anmeldung» entfernen" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "+ Element" }));
    const names = screen.getAllByLabelText("Name");
    expect(names).toHaveLength(2);
    fireEvent.change(names[1], { target: { value: "Fotos" } });
    fireEvent.change(screen.getByLabelText("Stichtag von Element 2"), { target: { value: "31.12.2026" } });
    fireEvent.blur(screen.getByLabelText("Stichtag von Element 2"));
    expect(latest.manual_elements.map((element) => element.name)).toEqual(["Anmeldung", "Fotos"]);

    fireEvent.click(screen.getByRole("button", { name: "+ Element" }));
    expect(screen.getAllByLabelText("Name")).toHaveLength(3);
    goTo(/5\. Zugriff/);
    expect(screen.getByRole("status")).toHaveTextContent("Jedes Element braucht einen Namen");
    goTo(/2\. Elemente/);
    fireEvent.click(screen.getByRole("button", { name: "Element «ohne Namen» entfernen" }));
    expect(screen.getAllByLabelText("Name")).toHaveLength(2);

    goTo(/3\. Verantwortlich/);
    expect(screen.queryByText(/keine verantwortliche Person/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Verantwortliche für «Fotos»" }));
    fireEvent.click(screen.getByRole("option", { name: /Anna Muster/ }));
    // Inaktive Personen stehen nicht zur Wahl
    expect(screen.queryByRole("option", { name: /Ehemalig/ })).not.toBeInTheDocument();
    expect(latest.manual_elements[1].responsible_participant_ids).toEqual(["p-anna"]);
    // Mit Verantwortlichen erscheint der persönliche Link
    expect(screen.getByRole("radiogroup", { name: "Persönlicher Link für Verantwortliche" })).toBeInTheDocument();

    const payload = assignmentPayload(latest);
    expect(payload.deadline).toBeNull();
    expect(payload.manual_elements).toEqual([
      { id: null, name: "Anmeldung", window_start: null, window_end: null, responsible_participant_ids: [] },
      { id: null, name: "Fotos", window_start: null, window_end: latest.manual_elements[1].window_end || null, responsible_participant_ids: ["p-anna"] },
    ]);
  });

  it("fragt vor dem Entfernen eines gespeicherten Elements nach", async () => {
    const confirm = vi.fn().mockResolvedValue(false);
    const saved = newManualElement("Anmeldung", { id: "el-1", key: "el-1" });
    render(<Harness start={{ ...manualStart, manual_elements: [saved, newManualElement("Fotos")] }} confirmRemoveElement={confirm} />);
    goTo(/2\. Elemente/);
    fireEvent.click(screen.getByRole("button", { name: "Element «Anmeldung» entfernen" }));
    await vi.waitFor(() => expect(confirm).toHaveBeenCalledWith("Anmeldung"));
    expect(screen.getAllByLabelText("Name")).toHaveLength(2);
    // Neue (noch nicht gespeicherte) Elemente gehen ohne Rückfrage
    fireEvent.click(screen.getByRole("button", { name: "Element «Fotos» entfernen" }));
    expect(screen.getAllByLabelText("Name")).toHaveLength(1);
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it("übernimmt Elemente aus der API und sendet sie nur bei Einzelabgaben", () => {
    const assignment = {
      id: "a-1", tenant_id: "t-1", title: "Lager", description: null, public_slug: "lager", source_type: "manual",
      tag_filter: null, offset_days_before: null, offset_days_after: null, cycle_config_id: null, cycle_offsets: [],
      list_definition_id: null, deadline: null, allowed_file_types: [], max_files_per_element: 5, max_file_size_mb: 20,
      sort_order: "date", auto_close: "never", responsible_participant_source: null, link_ids: [],
      manual_elements: [
        { id: "el-1", element_ref: "manual", name: "Anmeldung", window_start: "2026-12-01", window_end: "2026-12-31", is_default: true, responsible_participant_ids: ["p-ben"] },
      ],
      created_at: "2026-11-19T10:00:00Z", updated_at: "2026-11-19T10:00:00Z",
    } as SubmissionAssignment;
    const form = formFromAssignment(assignment);
    expect(form.manual_elements).toEqual([
      { key: "el-1", id: "el-1", name: "Anmeldung", window_start: "2026-12-01", window_end: "2026-12-31", responsible_participant_ids: ["p-ben"] },
    ]);
    expect(assignmentPayload(form).manual_elements?.[0]).toMatchObject({ id: "el-1", window_start: "2026-12-01" });
    expect(assignmentPayload({ ...form, source_type: "events", tag_filter: "x" })).not.toHaveProperty("manual_elements");
    // Ohne Elemente aus der API (Altbestand): ein Element mit Titel und bisherigem Stichtag
    const legacy = formFromAssignment({ ...assignment, manual_elements: [], deadline: "2026-10-01" });
    expect(legacy.manual_elements).toMatchObject([{ id: null, name: "Lager", window_end: "2026-10-01" }]);
  });
});

describe("Zeitfenster-Beispiel", () => {
  const events = [
    { title: "Alt", event_date: "2026-01-10", event_end_date: null, tag: "lager" },
    { title: "Badetag", event_date: "2026-03-14", event_end_date: null, tag: "lager" },
    { title: "Pfingstlager", event_date: "2026-05-23", event_end_date: "2026-05-25", tag: "lager" },
    { title: "Fremd", event_date: "2026-03-01", event_end_date: null, tag: "andere" },
  ];

  it("nimmt den nächsten Termin mit dem Tag, sonst den letzten", () => {
    expect(pickExampleEvent(events, "lager", "2026-03-01")?.title).toBe("Badetag");
    expect(pickExampleEvent(events, "lager", "2026-12-01")?.title).toBe("Pfingstlager");
    expect(pickExampleEvent(events, "keiner", "2026-03-01")).toBeNull();
  });

  it("rechnet wie das Backend, mehrtägige Termine ab dem letzten Tag", () => {
    const form = { ...initialForm, offset_days_before: 3, offset_days_after: 7 };
    expect(windowExample(form, events[1], t)).toBe("Beispiel: «Badetag» am 14.03.2026 → offen vom 11.03.2026 bis 21.03.2026.");
    expect(windowExample(form, events[2], t)).toContain("bis 01.06.2026");
    expect(windowExample({ ...initialForm, offset_days_after: 7 }, events[1], t)).toContain("sofort offen bis 21.03.2026");
    expect(windowExample(initialForm, events[1], t)).toContain("sofort offen, ohne Ende");
  });

  it("zeigt das Beispiel im Formular", () => {
    render(<Harness start={{ ...initialForm, tag_filter: "Scharanlass", offset_days_before: 0, offset_days_after: 2 }} />);
    fireEvent.click(screen.getByRole("button", { name: /2\. Zeitraum/ }));
    expect(screen.getByText(/^Beispiel: Termin am/)).toBeInTheDocument();
  });
});

describe("Vorlagen und Link", () => {
  it("füllt Quelle und Dateiregeln vor, Titel und Links bleiben", () => {
    const start = { ...initialForm, title: "Mein Titel", link_ids: ["link-1"] };
    const [reports, form, photos] = assignmentTemplates(t);
    expect(reports.apply(start)).toMatchObject({ title: "Mein Titel", link_ids: ["link-1"], source_type: "events", offset_days_after: 7 });
    expect(form.apply(start)).toMatchObject({ source_type: "manual", allowed_file_types: ["pdf"], max_files_per_element: 1, auto_close: "first_upload" });
    expect(photos.apply(start)).toMatchObject({ max_files_per_element: "", offset_days_after: 14 });
  });

  it("bietet die Vorlagen nur beim Anlegen an und wendet sie an", () => {
    render(<Harness start={{ ...initialForm, title: "Formular" }} />);
    fireEvent.click(screen.getByRole("button", { name: /Formular bis Stichtag/ }));
    expect(screen.getByRole("radio", { name: /Einzelabgabe/ })).toHaveAttribute("aria-checked", "true");
  });

  it("baut die öffentliche Adresse über den Standard-Link der Abgabe", () => {
    const links = [link({ id: "a", is_default: false, url: "https://box.example/a/" }), link({ id: "b", is_default: true, url: "https://box.example/b" })];
    expect(assignmentPublicUrl({ link_ids: ["a", "b"], public_slug: "fotos" }, links)).toBe("https://box.example/b/fotos");
    expect(assignmentPublicUrl({ link_ids: ["a"], public_slug: "fotos" }, links)).toBe("https://box.example/a/fotos");
    expect(assignmentPublicUrl({ link_ids: [], public_slug: "fotos" }, links)).toBeNull();
  });
});
