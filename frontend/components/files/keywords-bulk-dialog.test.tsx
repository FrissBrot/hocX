import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => showToastMock }));

import { KeywordsBulkDialog, MAX_KEYWORD_BULK } from "./keywords-bulk-dialog";

describe("KeywordsBulkDialog (Mehrfachbearbeitung Keywords)", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
  });

  it("fügt hinzu und entfernt markierte vorhandene Keywords in einem Aufruf", async () => {
    browserApiFetchMock.mockImplementation((url: string) =>
      url === "/api/files/keywords-summary"
        ? Promise.resolve([{ keyword: "Alt", count: 2 }, { keyword: "Bleibt", count: 1 }])
        : Promise.resolve({ updated: 2 })
    );
    const onDone = vi.fn();
    const onClose = vi.fn();
    render(<KeywordsBulkDialog open fileIds={["a", "b"]} onClose={onClose} onDone={onDone} />);
    expect(screen.getByText("Keywords für 2 Dateien")).toBeInTheDocument();
    const apply = screen.getByRole("button", { name: "Übernehmen" });
    expect(apply).toBeDisabled();

    const toggle = await screen.findByRole("button", { name: /Alt/ });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");

    const input = screen.getByLabelText("Hinzufügen", { selector: "input" });
    fireEvent.change(input, { target: { value: "Neu" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(apply);

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    const call = browserApiFetchMock.mock.calls.find(([url]) => url === "/api/files/bulk-keywords");
    expect(JSON.parse(call![1].body)).toEqual({ file_ids: ["a", "b"], add: ["Neu"], remove: ["Alt"] });
    expect(showToastMock).toHaveBeenCalledWith("2 Dateien aktualisiert", "success");
    expect(onClose).toHaveBeenCalled();
  });

  it("zeigt Fehler aus dem Backend und bleibt offen", async () => {
    browserApiFetchMock.mockImplementation((url: string) =>
      url === "/api/files/keywords-summary" ? Promise.resolve([]) : Promise.reject(new Error("Datei nicht gefunden"))
    );
    const onClose = vi.fn();
    render(<KeywordsBulkDialog open fileIds={["a"]} onClose={onClose} />);
    expect(await screen.findByText("Die Auswahl hat noch keine Keywords.")).toBeInTheDocument();
    const input = screen.getByLabelText("Hinzufügen", { selector: "input" });
    fireEvent.change(input, { target: { value: "Neu" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
    await waitFor(() => expect(showToastMock).toHaveBeenCalledWith("Datei nicht gefunden", "error"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("sperrt bei zu grosser Auswahl", () => {
    const ids = Array.from({ length: MAX_KEYWORD_BULK + 1 }, (_, index) => `id-${index}`);
    render(<KeywordsBulkDialog open fileIds={ids} onClose={() => {}} />);
    expect(screen.getByText(`Höchstens ${MAX_KEYWORD_BULK} Dateien auf einmal.`)).toBeInTheDocument();
    expect(browserApiFetchMock).not.toHaveBeenCalled();
  });
});
