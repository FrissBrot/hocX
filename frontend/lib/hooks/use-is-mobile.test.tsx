import { act, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ResponsiveView } from "@/components/mobile/responsive-view";
import { MAIN_CONTENT_ID } from "@/lib/a11y/focus";
import { useHoldViewportSwitch, useIsMobile, useViewportEpoch, ViewportProvider } from "@/lib/hooks/use-is-mobile";

// Steuerbares matchMedia: `setWidth` loest wie der Browser ein change-Ereignis aus.
function mockMatchMedia(initialMobile: boolean) {
  let matches = initialMobile;
  const listeners = new Set<() => void>();
  vi.stubGlobal("matchMedia", (query: string) => ({
    get matches() { return matches; },
    media: query,
    addEventListener: (_: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
  }));
  return (mobile: boolean) => act(() => {
    matches = mobile;
    listeners.forEach((listener) => listener());
  });
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main id={MAIN_CONTENT_ID}>
      <span data-testid="shell">{useIsMobile() ? "shell-mobil" : "shell-desktop"}</span>
      <span data-testid="epoch">{useViewportEpoch()}</span>
      {children}
    </main>
  );
}

function Dialog() {
  const [open, setOpen] = useState(false);
  useHoldViewportSwitch(open);
  return <button type="button" onClick={() => setOpen((value) => !value)}>{open ? "zu" : "auf"}</button>;
}

function Page() {
  return (
    <ResponsiveView
      mobile={<p>Mobil-Variante</p>}
      desktop={<div><p>Desktop-Variante</p><input aria-label="Notiz" /><Dialog /></div>}
    />
  );
}

function renderApp(initialMobile: boolean) {
  return render(
    <ViewportProvider initialMobile={initialMobile}>
      <Shell><Page /></Shell>
    </ViewportProvider>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ViewportProvider / ResponsiveView", () => {
  it("korrigiert die Server-Annahme beim ersten Laden sofort", () => {
    mockMatchMedia(true);
    renderApp(false);
    expect(screen.getByTestId("shell").textContent).toBe("shell-mobil");
    expect(screen.getByText("Mobil-Variante")).toBeTruthy();
    // Erste Korrektur: Shell baut wie vorher neu auf (Key), damit nichts als Layout-Shift zaehlt
    expect(screen.getByTestId("epoch").textContent).toBe("1");
  });

  it("wechselt Shell und Variante ohne offene Eingabe gemeinsam", () => {
    const setWidth = mockMatchMedia(false);
    renderApp(false);
    setWidth(true);
    expect(screen.getByTestId("shell").textContent).toBe("shell-mobil");
    expect(screen.getByText("Mobil-Variante")).toBeTruthy();
    // Spaetere Wechsel bauen die Shell nicht neu auf
    expect(screen.getByTestId("epoch").textContent).toBe("0");
  });

  it("schiebt den Variantenwechsel bei offenem Dialog auf, die Shell schaltet sofort", () => {
    const setWidth = mockMatchMedia(false);
    renderApp(false);
    act(() => screen.getByRole("button", { name: "auf" }).click());
    setWidth(true);
    expect(screen.getByTestId("shell").textContent).toBe("shell-mobil");
    expect(screen.getByText("Desktop-Variante")).toBeTruthy();
    act(() => screen.getByRole("button", { name: "zu" }).click());
    expect(screen.getByText("Mobil-Variante")).toBeTruthy();
  });

  it("schiebt den Variantenwechsel auf, solange in einem Feld der Seite getippt wird", async () => {
    vi.useFakeTimers();
    try {
      const setWidth = mockMatchMedia(false);
      renderApp(false);
      const field = screen.getByLabelText("Notiz") as HTMLInputElement;
      act(() => field.focus());
      setWidth(true);
      expect(screen.getByText("Desktop-Variante")).toBeTruthy();
      expect(document.activeElement).toBe(field);
      act(() => {
        field.blur();
        vi.runAllTimers();
      });
      expect(screen.getByText("Mobil-Variante")).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });
});
