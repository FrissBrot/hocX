import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

import { DEFAULT_EVENT_FIELD_CONFIG, publishEventFieldConfig, useEventFieldConfig } from "./use-event-field-config";

describe("useEventFieldConfig", () => {
  it("uses aliases, hides fields and leaves other fields alone", async () => {
    browserApiFetchMock.mockResolvedValue({
      ...DEFAULT_EVENT_FIELD_CONFIG,
      spezial1_ids: { label: "Küchenteam", hidden: false },
      spezial_text2: { label: "", hidden: true },
    });
    const { result } = renderHook(() => useEventFieldConfig());

    await waitFor(() => expect(result.current.label("spezial1_ids", "Spezial 1")).toBe("Küchenteam"));
    expect(result.current.label("spezial2_ids", "Spezial 2")).toBe("Spezial 2");
    expect(result.current.label("leadership_ids", "Leitung")).toBe("Leitung");
    expect(result.current.hidden("spezial_text2")).toBe(true);
    expect(result.current.hidden("location")).toBe(false);
    // Einmal pro Seite geladen
    renderHook(() => useEventFieldConfig());
    expect(browserApiFetchMock).toHaveBeenCalledTimes(1);

    // Speichern in den Einstellungen wirkt sofort in offenen Ansichten
    act(() => publishEventFieldConfig({ ...DEFAULT_EVENT_FIELD_CONFIG, spezial1_ids: { label: "Leiter", hidden: true } }));
    expect(result.current.label("spezial1_ids", "Spezial 1")).toBe("Leiter");
    expect(result.current.hidden("spezial1_ids")).toBe(true);
  });
});
