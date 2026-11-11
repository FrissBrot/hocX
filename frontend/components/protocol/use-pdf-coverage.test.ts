import { describe, expect, it } from "vitest";

import type { ProtocolElement } from "@/types/api";

import { pdfCoverageSignature, toPdfCoverage } from "./use-pdf-coverage";

const block = (id: string, overrides: Record<string, unknown> = {}) => ({ id, text_content: "", export_visible_snapshot: true, is_visible_snapshot: true, configuration_snapshot_json: {}, ...overrides });
const element = (id: string, blocks: ReturnType<typeof block>[]) => ({ id, export_visible_snapshot: true, blocks }) as unknown as ProtocolElement;

describe("PDF-Abdeckung im Editor", () => {
  it("ordnet die Antwort nach Punkt und Baustein", () => {
    expect(toPdfCoverage({ elements: [{ id: "e1", reason: "session_notes" }], blocks: [{ id: "b1", reason: "image_unavailable", count: 2 }, { id: "b2", reason: "block_not_exported" }] })).toEqual({
      elements: { e1: { reason: "session_notes" } },
      blocks: { b1: { reason: "image_unavailable", count: 2 }, b2: { reason: "block_not_exported" } },
    });
  });

  it("fragt beim Tippen nicht neu ab, wohl aber, wenn ein Block leer oder gefüllt wird", () => {
    const elements = [element("e1", [block("b1")])];
    const empty = pdfCoverageSignature(elements, { b1: "" }, {}, {});
    const typed = pdfCoverageSignature(elements, { b1: "Hallo" }, {}, {});
    const more = pdfCoverageSignature(elements, { b1: "Hallo Welt" }, {}, {});
    expect(typed).not.toBe(empty);
    expect(more).toBe(typed);
    expect(pdfCoverageSignature([element("e1", [block("b1", { export_visible_snapshot: false })])], { b1: "Hallo" }, {}, {})).not.toBe(typed);
  });
});
