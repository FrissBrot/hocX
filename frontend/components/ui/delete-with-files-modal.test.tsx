import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ browserApiFetch: vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn() }));

import { DeleteWithFilesModal, DeletionPreviewFile } from "./delete-with-files-modal";

const file = (overrides: Partial<DeletionPreviewFile>): DeletionPreviewFile => ({
  id: "f1",
  name: "bild.png",
  mime_type: "image/png",
  is_image: true,
  thumbnail_url: null,
  created_at: null,
  group: "protocol_image",
  used_elsewhere: false,
  label: null,
  ...overrides,
});

describe("DeleteWithFilesModal", () => {
  const files = [
    file({ id: "a", name: "a.png" }),
    file({ id: "b", name: "b.png" }),
    file({ id: "c", name: "geteilt.png", used_elsewhere: true }),
  ];

  it("selects every deletable file by default and never the shared one", () => {
    const onConfirm = vi.fn();
    render(<DeleteWithFilesModal open title="Protokoll löschen" message="Sicher?" files={files} busy={false} onCancel={vi.fn()} onConfirm={onConfirm} />);

    const shared = screen.getByText("geteilt.png").closest("label")!.querySelector("input")!;
    expect(shared).toBeDisabled();
    expect(shared).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Löschen mit 2 Dateien" }));
    expect(onConfirm).toHaveBeenCalledWith(["a", "b"]);
  });

  it("passes only the files that stay selected and announces the kept ones", () => {
    const onConfirm = vi.fn();
    render(<DeleteWithFilesModal open title="Protokoll löschen" message="Sicher?" files={files} busy={false} onCancel={vi.fn()} onConfirm={onConfirm} />);

    fireEvent.click(screen.getByText("a.png").closest("label")!.querySelector("input")!);

    expect(screen.getByText("Eine nicht ausgewählte Datei wird in die Galerie übernommen.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Löschen mit einer Datei" }));
    expect(onConfirm).toHaveBeenCalledWith(["b"]);
  });
});
