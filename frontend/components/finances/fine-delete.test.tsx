import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useFineDelete, type FineDeleteOutcome } from "./fine-delete";

const fetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (...args: unknown[]) => fetchMock(...args) }));
const confirmMock = vi.fn();
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirmMock }));
const toastMock = vi.fn();
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toastMock }));

let requestDelete: ReturnType<typeof useFineDelete>["requestDelete"];

function Harness({ protocolId }: { protocolId?: string }) {
  const hook = useFineDelete(protocolId);
  requestDelete = hook.requestDelete;
  return <>{hook.dialog}</>;
}

beforeEach(() => { fetchMock.mockReset(); fetchMock.mockResolvedValue(undefined); confirmMock.mockReset(); toastMock.mockReset(); });

describe("useFineDelete", () => {
  it("löscht eine Busse aus offenem Ursprung nach Rückfrage ohne Begründung", async () => {
    confirmMock.mockResolvedValue(true);
    render(<Harness protocolId="p-2" />);

    let outcome: FineDeleteOutcome = null;
    await act(async () => { outcome = await requestDelete({ id: "f-1", participant_name_snapshot: "Anna", delete_requires_reason: false }); });

    expect(outcome).toBe("hard");
    expect(fetchMock).toHaveBeenCalledWith("/api/fines/f-1", { method: "DELETE" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("verlangt bei mitgeführter Busse eine Begründung und sendet sie mit dem Protokoll", async () => {
    render(<Harness protocolId="p-2" />);

    let pending!: Promise<FineDeleteOutcome>;
    act(() => { pending = requestDelete({ id: "f-1", participant_name_snapshot: "Anna", delete_requires_reason: true }); });
    const submit = await screen.findByRole("button", { name: "Löschen" });
    expect(confirmMock).not.toHaveBeenCalled();
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox", { name: /Begründung/ }), { target: { value: "  Doppelt erfasst " } });
    fireEvent.click(submit);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledWith("/api/fines/f-1", {
      method: "DELETE",
      body: JSON.stringify({ reason: "Doppelt erfasst", protocol_id: "p-2" }),
    });
    await expect(pending).resolves.toBe("soft");
  });

  it("ohne offenes Protokoll: übersetzte Meldung statt rohem Backend-Text", async () => {
    // Backend (FineDeleteError no_open_protocol): 409, Text nur deutsch
    fetchMock.mockRejectedValue(Object.assign(new Error("Es gibt kein offenes Protokoll, in dem die Löschung aufgeführt werden kann"), {
      status: 409, detail: { code: "no_open_protocol", message: "Es gibt kein offenes Protokoll, in dem die Löschung aufgeführt werden kann" },
    }));
    render(<Harness />);

    act(() => { void requestDelete({ id: "f-1", participant_name_snapshot: "Anna", delete_requires_reason: true }); });
    fireEvent.change(await screen.findByRole("textbox", { name: /Begründung/ }), { target: { value: "Doppelt" } });
    fireEvent.click(screen.getByRole("button", { name: "Löschen" }));

    await waitFor(() => expect(toastMock).toHaveBeenCalled());
    expect(toastMock).toHaveBeenCalledWith(
      "Es gibt kein offenes Protokoll, in dem die Löschung aufgeführt werden kann. Lege zuerst ein Protokoll an.", "error",
    );
  });

  it("bricht ohne Löschen ab, wenn der Dialog geschlossen wird", async () => {
    render(<Harness />);

    let pending!: Promise<FineDeleteOutcome>;
    act(() => { pending = requestDelete({ id: "f-1", participant_name_snapshot: "Anna", delete_requires_reason: true }); });
    fireEvent.click(await screen.findByRole("button", { name: "Abbrechen" }));

    await expect(pending).resolves.toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
