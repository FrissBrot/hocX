import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

import { PlaceFilterChip, PlaceSuggestions } from "./photo-place-filter";

const HIT = { key: "gn:2660191", name: "Kandersteg", kind: "village", admin1_code: "BE", admin1_name: "Bern", country_code: "CH", locality_name: null, radius_km: 5 };

describe("PlaceSuggestions (Treffertyp «Ort»)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    browserApiFetchMock.mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it("sucht erst ab 3 Zeichen und wählt einen Ort per Tastatur", async () => {
    browserApiFetchMock.mockResolvedValue([HIT]);
    const onSelect = vi.fn();
    const { rerender } = render(<PlaceSuggestions query="ka" onSelect={onSelect} />);
    await act(async () => { vi.advanceTimersByTime(400); });
    expect(browserApiFetchMock).not.toHaveBeenCalled();

    rerender(<PlaceSuggestions query="kander" onSelect={onSelect} />);
    await act(async () => { vi.advanceTimersByTime(400); });
    expect(browserApiFetchMock.mock.calls[0][0]).toBe("/api/places/search?q=kander&limit=4");
    const button = screen.getByRole("button", { name: /Kandersteg · Dorf · BE/ });
    button.focus();
    expect(button).toHaveFocus();
    fireEvent.click(button);
    expect(onSelect).toHaveBeenCalledWith(HIT);
  });
});

describe("PlaceFilterChip", () => {
  it("zeigt Ort und Radius, erweitert um 10 km und entfernt den Filter", () => {
    const onWiden = vi.fn();
    const onRemove = vi.fn();
    render(<PlaceFilterChip filter={{ key: HIT.key, label: "Kandersteg BE", radiusKm: 5, baseRadiusKm: 5 }} onWiden={onWiden} onRemove={onRemove} />);
    expect(screen.getByText("Umgebung Kandersteg BE · 5 km")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Umkreis um 10 km erweitern" }));
    fireEvent.click(screen.getByRole("button", { name: "Ortsfilter «Kandersteg BE» entfernen" }));
    expect(onWiden).toHaveBeenCalledOnce();
    expect(onRemove).toHaveBeenCalledOnce();
  });
});
