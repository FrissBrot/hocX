import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  FormState,
  SubmissionAssignmentFormModal,
  describeAssignment,
  formProblem,
  initialForm,
  publicUrlParts,
  slugify,
} from "./submission-assignment-form";
import { SubmissionLink } from "@/types/api";

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

describe("formProblem", () => {
  it("verlangt Titel und für Termine einen Tag", () => {
    expect(formProblem(initialForm)).toBe("Titel fehlt");
    expect(formProblem({ ...initialForm, title: "Bilder" })).toBe("Tag-Filter fehlt");
    expect(formProblem({ ...initialForm, title: "Bilder", tag_filter: "Scharanlass" })).toBeNull();
  });

  it("verlangt für Listen eine Liste, für manuelle Abgaben nichts weiter", () => {
    expect(formProblem({ ...initialForm, title: "Bilder", source_type: "list" })).toBe("Liste fehlt");
    expect(formProblem({ ...initialForm, title: "Bilder", source_type: "manual" })).toBeNull();
  });

  it("verlangt bei aktivem Zyklus-Filter mindestens einen Zyklus", () => {
    const form = { ...initialForm, title: "Bilder", tag_filter: "x", cycle_config_id: "cfg", cycle_offsets: [] };
    expect(formProblem(form)).toMatch(/Zyklus/);
  });
});

describe("describeAssignment", () => {
  it("beschreibt das Zeitfenster einer Termin-Abgabe", () => {
    const form = { ...initialForm, tag_filter: "Scharanlass", offset_days_before: 7, offset_days_after: 3 };
    expect(describeAssignment(form, null)).toBe(
      "Jeder Termin mit dem Tag «Scharanlass» bekommt ein eigenes Abgabefeld. Es öffnet 7 Tage vor dem Termin und schliesst 3 Tage danach.",
    );
  });

  it("beschreibt Termin-Abgaben ohne Zeitfenster als offen bis zum manuellen Schliessen", () => {
    expect(describeAssignment({ ...initialForm, tag_filter: "x" }, null)).toContain("bleibt offen, bis es manuell geschlossen wird");
  });

  it("beschreibt manuelle Abgaben mit einem einzigen Abgabefeld und optionalem Stichtag", () => {
    const manual = { ...initialForm, source_type: "manual" as const };
    expect(describeAssignment(manual, null)).toContain("einziges Abgabefeld");
    expect(describeAssignment({ ...manual, deadline: "2026-12-31" }, null)).toContain("bis 31.12.2026");
  });

  it("nennt bei Listen den Namen der Liste", () => {
    expect(describeAssignment({ ...initialForm, source_type: "list" }, "Vorstand")).toContain("«Vorstand»");
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
  it("bietet Termine, Liste und Manuell als Verknüpfung an", () => {
    render(<Harness />);
    const radios = screen.getAllByRole("radio");
    expect(radios.map((r) => r.textContent)).toEqual([
      expect.stringContaining("Termine"),
      expect.stringContaining("Liste"),
      expect.stringContaining("Manuell"),
    ]);
    expect(radios[0]).toHaveAttribute("aria-checked", "true");
  });

  it("blendet bei «Manuell» Tag-Filter, Zeitfenster und Sortierung aus und erlaubt das Speichern ohne Tag", () => {
    const onSubmit = vi.fn();
    render(<Harness start={{ ...initialForm, title: "Vereinsfotos", public_slug: "vereinsfotos" }} onSubmit={onSubmit} />);
    const submit = screen.getByRole("button", { name: "Abgabe erstellen" });
    expect(submit).toBeDisabled();
    expect(screen.getByText("Tag-Filter")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: /Manuell/ }));

    expect(screen.queryByText("Tag-Filter")).not.toBeInTheDocument();
    expect(screen.queryByText("Zeitfenster")).not.toBeInTheDocument();
    expect(screen.queryByText("Sortierung")).not.toBeInTheDocument();
    expect(screen.getByText("Stichtag")).toBeInTheDocument();
    expect(submit).toBeEnabled();

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
    expect(screen.getByText("alle erlaubt")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Alle" })[0]);
    expect(screen.getByText("1 ausgewählt")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keine" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: ".png" }));
    expect(screen.getByText("2 ausgewählt")).toBeInTheDocument();
  });
});
