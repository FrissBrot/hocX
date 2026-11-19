import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RevisionsModal } from "./revisions-modal";

const api = vi.hoisted(() => ({ studioApi: { revisions: vi.fn(), compare: vi.fn(), restoreRevision: vi.fn() } }));
const { toast, confirm } = vi.hoisted(() => ({ toast: vi.fn(), confirm: vi.fn() }));

vi.mock("@/lib/documents/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/documents/api")>()), ...api }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirm }));

function revision(id: string, revision_no: number, status: string) {
  return { id, revision_no, status, lock_version: 1, brand_mode: "follow", schema_version: 1, note: null, created_at: "", updated_at: "2026-11-01T10:00:00Z", published_at: null, created_by_name: null, template_id: null, brand_id: null };
}

const template = { id: "tpl", name: "Protokoll", editable: true } as never;

describe("RevisionsModal", () => {
  beforeEach(() => {
    [toast, confirm, ...Object.values(api.studioApi)].forEach((fn) => fn.mockReset());
    api.studioApi.revisions.mockResolvedValue([revision("r1", 1, "superseded"), revision("r2", 2, "published")]);
  });

  // Der Strukturvergleich (template_service.compare_revisions) meldet jedes geänderte Feld eines
  // Knotens. Datenblöcke tragen «appearance» und «block_appearance» (Bausteine einzeln gestalten):
  // ohne Übersetzung zeigte der Vergleich den rohen Schlüssel documentStudio.revisions.field.…
  it("names changed appearance fields of a data block in the comparison", async () => {
    api.studioApi.compare.mockResolvedValue({
      nodes: [{ change: "modified", node_id: "n1", type: "data_block", name: "", area: "body", fields: ["appearance", "block_appearance"] }],
      settings: [],
      masters: [],
    });
    render(<RevisionsModal template={template} onClose={() => undefined} onRestored={() => undefined} />);

    fireEvent.click(await screen.findByRole("checkbox", { name: /Revision 1/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Revision 2/ }));

    const differences = await screen.findByRole("region", { name: "Unterschiede" });
    await waitFor(() => expect(differences.textContent).toContain("Fachkomponente"));
    expect(differences.textContent).not.toContain("documentStudio.");
    expect(differences.textContent).not.toMatch(/\bblock_appearance\b|\bappearance\b/);
  });
});
