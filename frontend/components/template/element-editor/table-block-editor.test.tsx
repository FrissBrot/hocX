import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ browserApiFetch: vi.fn(() => Promise.resolve([])), browserApiBaseUrl: "" }));

import { newBlockForm, type BlockForm } from "./block-form";
import { dropSide, EVENT_FIELDS, eventFieldsOf, moveEnabledField, orderedFields, TableBlockSection, todoFieldsOf } from "./table-block-editor";

const data = { participants: [], events: [], lists: [], listEntries: {}, ensureListEntries: () => undefined, knownEventTags: [], tagConfig: {} };

function formWith(config: Record<string, unknown>): BlockForm {
  const base = newBlockForm(6, 1, 10);
  return { ...base, config: { ...base.config, rows: [], ...config } };
}

describe("orderedFields", () => {
  it("behält die gespeicherte Reihenfolge und hängt nicht gespeicherte Felder in Standardreihenfolge an", () => {
    const fields = orderedFields(
      [
        { field: "location", label: "Wo", enabled: true },
        { field: "title", label: "", enabled: true },
        { field: "unbekannt", label: "", enabled: true },
        { field: "location", label: "doppelt", enabled: false },
      ],
      EVENT_FIELDS
    );
    expect(fields.slice(0, 3).map((entry) => entry.field)).toEqual(["location", "title", "description"]);
    expect(fields[0]).toEqual({ field: "location", label: "Wo", enabled: true });
    expect(fields).toHaveLength(EVENT_FIELDS.length);
  });

  it("lässt bestehende Bausteine in Standardreihenfolge unverändert", () => {
    const saved = EVENT_FIELDS.map((field) => ({ field, label: "", enabled: field === "title" || field === "location" }));
    expect(eventFieldsOf(formWith({ event_fields: saved }))).toEqual(saved);
  });

  it("gilt auch für Pendenzfelder", () => {
    const fields = todoFieldsOf(formWith({ todo_fields: [{ field: "status", label: "", enabled: true }] }));
    expect(fields.map((entry) => entry.field)).toEqual(["status", "task", "description", "participant", "due_date", "origin"]);
  });
});

describe("dropSide", () => {
  it("zeigt die Einfügelinie dort, wo moveItem die Zeile ablegt", () => {
    expect(dropSide(0, 2)).toBe("after"); // nach unten gezogen: hinter das Ziel
    expect(dropSide(3, 1)).toBe("before"); // nach oben gezogen: vor das Ziel
    expect(dropSide(2, 2)).toBeNull();
    expect(dropSide(-1, 2)).toBeNull();
  });
});

describe("moveEnabledField", () => {
  const fields = [
    { field: "title", label: "", enabled: true },
    { field: "tag", label: "", enabled: false },
    { field: "location", label: "", enabled: true },
    { field: "event_date", label: "", enabled: true },
  ];

  it("verschiebt innerhalb der aktivierten Felder, deaktivierte folgen danach", () => {
    expect(moveEnabledField(fields, "event_date", { target: "title" }).map((entry) => entry.field)).toEqual(["event_date", "title", "location", "tag"]);
    expect(moveEnabledField(fields, "title", { offset: 1 }).map((entry) => entry.field)).toEqual(["location", "title", "event_date", "tag"]);
  });

  it("ändert an den Rändern nichts", () => {
    expect(moveEnabledField(fields, "title", { offset: -1 })).toBe(fields);
    expect(moveEnabledField(fields, "event_date", { offset: 1 })).toBe(fields);
  });
});

function enabledOrder(form: BlockForm) {
  return (form.config.event_fields as Array<{ field: string; enabled: boolean }>).filter((entry) => entry.enabled).map((entry) => entry.field);
}

describe("TableBlockSection: Zeilen aus dem Termin", () => {
  function setup(openKey: string | null = null) {
    const onChange = vi.fn();
    const form = formWith({
      repeat_source: "event",
      event_fields: [
        { field: "location", label: "Wo", enabled: true },
        { field: "title", label: "Was", enabled: true },
      ],
    });
    render(<TableBlockSection form={form} onChange={onChange} data={data} openKey={openKey} onOpenKey={() => undefined} previewItem={null} />);
    return onChange;
  }

  it("zeigt die Terminzeilen in gespeicherter Reihenfolge", () => {
    setup();
    const labels = [...document.querySelectorAll(".table-block-row-event .table-block-row-label")].map((node) => node.textContent);
    expect(labels).toEqual(["Wo", "Was"]);
  });

  it("sortiert per Tastatur-Button und per Ziehen", () => {
    const onChange = setup("e:location");
    fireEvent.click(screen.getByRole("button", { name: "Nach unten" }));
    expect(enabledOrder(onChange.mock.calls[0][0] as BlockForm)).toEqual(["title", "location"]);

    const rows = document.querySelectorAll(".table-block-row-event");
    fireEvent.dragStart(rows[1], { dataTransfer: { effectAllowed: "" } });
    fireEvent.drop(rows[0], { dataTransfer: {} });
    expect(enabledOrder(onChange.mock.calls[1][0] as BlockForm)).toEqual(["title", "location"]);
  });
});
