/**
 * Kurze Meldung für Screenreader (aria-live="polite"), z. B. nach dem Verschieben per Tastatur,
 * wenn sich sichtbar nur die Reihenfolge ändert. Eine gemeinsame Live-Region in <body>.
 */
let region: HTMLElement | null = null;

export function announce(message: string): void {
  if (typeof document === "undefined") return;
  if (!region || !region.isConnected) {
    region = document.createElement("div");
    region.className = "visually-hidden";
    region.setAttribute("aria-live", "polite");
    region.setAttribute("role", "status");
    document.body.appendChild(region);
  }
  // Leeren und neu setzen, damit dieselbe Meldung zweimal hintereinander gelesen wird
  region.textContent = "";
  const target = region;
  window.setTimeout(() => {
    target.textContent = message;
  }, 30);
}
