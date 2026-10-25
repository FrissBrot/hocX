import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { ExamplesModal } from "./examples-modal";

const api = vi.hoisted(() => ({
  studioApi: {
    listExamples: vi.fn(),
    importExample: vi.fn(),
    exampleThumbnailUrl: vi.fn((key: string) => `/thumb/${key}.png`),
  },
}));
const toast = vi.hoisted(() => vi.fn());

vi.mock("@/lib/documents/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/documents/api")>()), ...api }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));

beforeEach(() => {
  vi.clearAllMocks();
  api.studioApi.listExamples.mockResolvedValue([
    { key: "protocol_band", document_type: "protocol" },
    { key: "protocol_law", document_type: "protocol" },
  ]);
});

it("lists the examples with name, description and thumbnail", async () => {
  render(<ExamplesModal onClose={vi.fn()} onImported={vi.fn()} />);
  expect(await screen.findByText("Protokoll Farbband")).toBeInTheDocument();
  expect(screen.getByText("Protokoll Kanzlei")).toBeInTheDocument();
  expect(screen.getByText(/zentrierter Briefkopf/)).toBeInTheDocument();
  expect(api.studioApi.exampleThumbnailUrl).toHaveBeenCalledWith("protocol_band");
});

it("imports an example under its translated name and hands over the new template", async () => {
  const created = { id: "tpl-1" };
  api.studioApi.importExample.mockResolvedValue(created);
  const onImported = vi.fn();
  render(<ExamplesModal onClose={vi.fn()} onImported={onImported} />);
  await screen.findByText("Protokoll Kanzlei");
  fireEvent.click(screen.getAllByRole("button", { name: "Hinzufügen" })[1]);
  await waitFor(() => expect(onImported).toHaveBeenCalledWith(created));
  expect(api.studioApi.importExample).toHaveBeenCalledWith("protocol_law", "Protokoll Kanzlei");
  expect(toast).toHaveBeenCalledWith(expect.stringContaining("Beispiel hinzugefügt"), "success");
});
