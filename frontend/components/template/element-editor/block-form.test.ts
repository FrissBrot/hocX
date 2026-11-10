import { describe, expect, it } from "vitest";
import type { ElementDefinitionBlock } from "@/types/api";
import { blockFormFromBlock, blockPayload, changeElementType, newBlockForm, rowTypeAllowed, setRepeatSource } from "./block-form";

const block = (element_type_id: number, configuration_json: Record<string, unknown>, extra: Partial<ElementDefinitionBlock> = {}): ElementDefinitionBlock => ({
  id: 1, title: "Block", description: null, block_title: null, default_content: null, copy_from_last_protocol: false,
  element_type_id, render_type_id: 2, is_editable: false, allows_multiple_values: false, export_visible: true,
  is_visible: true, sort_index: 10, render_order: 10, configuration_json, ...extra,
});

describe("block-form", () => {
  it("speichert nur, was der Typ nutzt (kein chart_type im Textblock)", () => {
    const payload = blockPayload(newBlockForm(1, 1, 10));
    expect(payload.configuration_json).toEqual({ block_kind: "text", repeat_source: "none" });
    expect(payload.render_type_id).toBe(2);
  });

  it("Render-Typ und Mehrfachwerte kommen aus der Registry", () => {
    const payload = blockPayload(newBlockForm(2, 1, 10));
    expect(payload.render_type_id).toBe(3);
    expect(payload.allows_multiple_values).toBe(true);
  });

  it("Typwechsel beim Bearbeiten behält «editierbar» (B3), beim Anlegen gilt der Typ-Default", () => {
    const form = blockFormFromBlock(block(1, {}, { is_editable: false }));
    expect(changeElementType(form, 6, "edit").is_editable).toBe(false);
    expect(changeElementType({ ...form, is_editable: true }, 7, "create").is_editable).toBe(false);
  });

  it("Typwechsel behält erlaubte Wiederholung und teilt Zeilen zwischen Tabelle und Matrix", () => {
    const repeating = setRepeatSource(newBlockForm(1, 1, 10), "event");
    expect(changeElementType(repeating, 6, "edit").config.repeat_source).toBe("event");
    expect(changeElementType(repeating, 7, "edit").config.repeat_source).toBe("none");

    const table = blockFormFromBlock(block(6, { rows: [{ id: "1", label: "Leitung", row_type: "participant" }, { id: "2", label: "L", row_type: "list_entry" }] }));
    const matrix = changeElementType(table, 11, "edit");
    expect(matrix.config.rows.map((row: { label: string }) => row.label)).toEqual(["Leitung"]);
  });

  it("Behavior-Schalter und Platzhalter werden gespeichert (B1, B2)", () => {
    const form = blockFormFromBlock(block(11, {
      mode: "manual",
      rows: [{ id: "1", label: "A", row_type: "text" }],
      columns: [{ id: "c1", title: "Spalte", title_placeholder: "Name" }],
    }, { title_as_subtitle: false }));
    const payload = blockPayload({ ...form, export_visible: false, is_visible: false });
    expect(payload.title_as_subtitle).toBe(false);
    expect(payload.export_visible).toBe(false);
    expect(payload.is_visible).toBe(false);
    expect((payload.configuration_json.columns as Array<Record<string, unknown>>)[0].title_placeholder).toBe("Name");
  });

  it("Vorgabetext nur bei Typen mit Inhalt", () => {
    const form = { ...newBlockForm(9, 1, 10), default_content: "x" };
    expect(blockPayload(form).default_content).toBeNull();
  });

  it("Zeilentypen je Blocktyp", () => {
    expect(rowTypeAllowed("matrix", "events")).toBe(true);
    expect(rowTypeAllowed("form", "events")).toBe(false);
    expect(rowTypeAllowed("form", "list_entry")).toBe(true);
    expect(rowTypeAllowed("matrix", "7")).toBe(true);
    expect(rowTypeAllowed("form", "7")).toBe(false);
  });
});
