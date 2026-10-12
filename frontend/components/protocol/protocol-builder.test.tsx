import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();
const confirmMock = vi.fn();
const refreshMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => showToastMock }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirmMock }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: refreshMock }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/hooks/use-refresh-on-restore", () => ({ useRefreshOnRestore: () => undefined }));
vi.mock("@/lib/hooks/use-infinite-scroll", () => ({ useInfiniteScroll: () => () => undefined }));

import { ProtocolBuilder } from "./protocol-builder";
import { ProtocolSummary } from "@/types/api";

function makeProtocol(overrides: Partial<ProtocolSummary> = {}): ProtocolSummary {
  return {
    id: "protocol-1",
    template_id: "template-1",
    protocol_number: "P-7",
    title: "7. Hock",
    protocol_date: "2026-10-20",
    status: "geplant",
    ...overrides,
  } as ProtocolSummary;
}

const preview = {
  applied: false,
  added_elements: ["Neu"],
  updated_elements: ["Notizen", "Traktanden"],
  removed_elements: ["Alt"],
  kept_elements: ["Mit Inhalt"],
  added_blocks: 1,
  removed_blocks: 1,
  kept_blocks: 0,
};

function openMenuAndSync() {
  fireEvent.click(screen.getByRole("button", { name: "Aktionen für P-7" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "Elemente aus Vorlage neu laden" }));
}

describe("ProtocolBuilder: Elemente aus Vorlage neu laden", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    confirmMock.mockReset();
    refreshMock.mockReset();
    browserApiFetchMock.mockImplementation((path: string) =>
      Promise.resolve(path.endsWith("dry_run=true") ? preview : { ...preview, applied: true })
    );
  });

  it("zeigt die Vorschau und wendet den Abgleich nach Bestätigung an", async () => {
    confirmMock.mockResolvedValue(true);
    render(<ProtocolBuilder initialProtocols={[makeProtocol()]} templates={[]} />);

    openMenuAndSync();

    await waitFor(() => expect(showToastMock).toHaveBeenCalledWith("Elemente aus der Vorlage neu geladen", "success"));
    expect(browserApiFetchMock).toHaveBeenCalledWith("/api/protocols/protocol-1/sync-template?dry_run=true", { method: "POST" });
    expect(browserApiFetchMock).toHaveBeenCalledWith("/api/protocols/protocol-1/sync-template", { method: "POST" });
    const { message, title } = confirmMock.mock.calls[0][0];
    expect(title).toBe("Elemente aus Vorlage neu laden?");
    expect(message).toContain("2 Elemente werden aktualisiert, 1 kommt neu dazu, 1 wird entfernt.");
    expect(message).toContain("Entfernt (leer, nicht mehr in der Vorlage): Alt.");
    expect(message).toContain("bleibt am Ende stehen: Mit Inhalt.");
    expect(refreshMock).toHaveBeenCalled();
  });

  it("ändert nichts, wenn die Rückfrage abgebrochen wird", async () => {
    confirmMock.mockResolvedValue(false);
    render(<ProtocolBuilder initialProtocols={[makeProtocol()]} templates={[]} />);

    openMenuAndSync();

    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    expect(browserApiFetchMock).toHaveBeenCalledTimes(1);
    expect(showToastMock).not.toHaveBeenCalled();
  });

  it("bietet den Abgleich für abgeschlossene Protokolle nicht an", () => {
    render(<ProtocolBuilder initialProtocols={[makeProtocol({ status: "abgeschlossen" })]} templates={[]} />);

    fireEvent.click(screen.getByRole("button", { name: "Aktionen für P-7" }));

    expect(screen.queryByRole("menuitem", { name: "Elemente aus Vorlage neu laden" })).toBeNull();
  });
});
