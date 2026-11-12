import { fireEvent, render, screen, within } from "@testing-library/react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  FormState,
  SubmissionAssignmentFormModal,
  describeAssignment,
  formProblem,
  initialForm,
  assignmentTemplates,
  pickExampleEvent,
  publicUrlParts,
  slugify,
  windowExample,
} from "./submission-assignment-form";
import { assignmentPublicUrl } from "./submission-share-link";
import { SubmissionLink } from "@/types/api";

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

function Harness({ start = initialForm, onSubmit = vi.fn() }: { start?: FormState; onSubmit?: () => void }) {
  const [form, setForm] = useState<FormState>(start);
  return (
    <SubmissionAssignmentFormModal
      open
      editing={false}
      tenantName="Verein Alpina"
      form={form}
      setForm={setForm}
      links={[link(), link({ id: "link-2", name: "Vorstand intern", is_default: false })]}
      availableLists={[]}
      availableTags={["Scharanlass", "Hauptversammlung"]}
      availableCycleConfigs={[]}
      onSubmit={onSubmit}
      onClose={vi.fn()}
      onManageLinks={vi.fn()}
    />
  );
}

describe("describeAssignment – automatisch schliessen", () => {
  const base: FormState = { ...initialForm, title: "Bericht", source_type: "manual" };

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
    fireEvent.click(screen.getByRole("button", { name: /Erweitert/ }));
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

  it("verlangt für Listen eine Liste, für manuelle Abgaben nichts weiter", () => {
    expect(formProblem({ ...initialForm, title: "Bilder", source_type: "list" }, t)).toBe("Liste fehlt");
    expect(formProblem({ ...initialForm, title: "Bilder", source_type: "manual" }, t)).toBeNull();
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

  it("beschreibt manuelle Abgaben mit einem einzigen Abgabefeld und optionalem Stichtag", () => {
    const manual = { ...initialForm, source_type: "manual" as const };
    expect(describeAssignment(manual, null, t)).toContain("einziges Abgabefeld");
    expect(describeAssignment({ ...manual, deadline: "2026-12-31" }, null, t)).toContain("bis 31.12.2026");
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

describe("SubmissionAssignmentFormModal", () => {
  it("bietet Termine, Liste und Einzelabgabe als Verknüpfung an", () => {
    render(<Harness />);
    const radios = within(screen.getByRole("radiogroup", { name: "Verknüpfung" })).getAllByRole("radio");
    expect(radios.map((r) => r.textContent)).toEqual([
      expect.stringContaining("Termine"),
      expect.stringContaining("Liste"),
      expect.stringContaining("Einzelabgabe"),
    ]);
    expect(radios[0]).toHaveAttribute("aria-checked", "true");
  });

  it("blendet bei «Einzelabgabe» Tag-Filter, Zeitfenster und Sortierung aus und erlaubt das Speichern ohne Tag", () => {
    const onSubmit = vi.fn();
    render(<Harness start={{ ...initialForm, title: "Vereinsfotos", public_slug: "vereinsfotos" }} onSubmit={onSubmit} />);
    const submit = screen.getByRole("button", { name: "Abgabe erstellen" });
    expect(submit).toBeDisabled();
    expect(screen.getByText("Tag-Filter")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Noch offen: Tag-Filter fehlt");

    fireEvent.click(screen.getByRole("radio", { name: /Einzelabgabe/ }));

    expect(screen.queryByText("Tag-Filter")).not.toBeInTheDocument();
    expect(screen.queryByText("Zeitfenster")).not.toBeInTheDocument();
    expect(screen.queryByText("Sortierung")).not.toBeInTheDocument();
    expect(screen.getByText("Stichtag")).toBeInTheDocument();
    expect(submit).toBeEnabled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    fireEvent.click(submit);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("zeigt Eyebrow, öffentliche Adresse mit Slug und den Standard-Link", () => {
    render(<Harness start={{ ...initialForm, title: "Bilder", public_slug: "bilder", link_ids: ["link-1"] }} />);
    expect(screen.getByText("Neue Abgabe")).toBeInTheDocument();
    expect(screen.getByText("Verein Alpina")).toBeInTheDocument();
    expect(screen.getByText("bilder").tagName).toBe("STRONG");
    expect(screen.getByText("Standard", { selector: "small" })).toBeInTheDocument();
  });

  it("leitet den Slug beim Tippen des Titels ab", () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText("Titel"), { target: { value: "Bilder Scharanlass" } });
    expect(screen.getByLabelText("Titel")).toHaveValue("Bilder Scharanlass");
  });

  it("zählt gewählte Dateitypen und wechselt zwischen «Alle» und «Keine»", () => {
    render(<Harness />);
    expect(screen.queryByText("alle erlaubt")).not.toBeInTheDocument(); // in «Erweitert»
    fireEvent.click(screen.getByRole("button", { name: /Erweitert/ }));
    expect(screen.getByText("alle erlaubt")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Alle" })[0]);
    expect(screen.getByText("1 ausgewählt")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keine" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: ".png" }));
    expect(screen.getByText("2 ausgewählt")).toBeInTheDocument();
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
