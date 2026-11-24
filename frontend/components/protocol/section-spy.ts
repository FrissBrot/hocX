// Aktiver Punkt beim Scrollen (Design «Protokoll-Editor 1a»): ein IntersectionObserver auf den
// Punkten statt Messen in jedem Scroll-Frame. Aktiv ist der oberste Punkt, der das obere Drittel
// des Dokuments berührt (rootMargin unten -70 %). Ein Observer meldet nur Änderungen, deshalb
// merkt sich der Spy die gerade sichtbaren Punkte und wählt daraus in Dokumentreihenfolge.

export const SPY_ROOT_MARGIN = "0px 0px -70% 0px";

export type SectionSpy = {
  /** Punkte neu beobachten (nach Änderung der Reihenfolge oder Anzahl). */
  observe: (sections: HTMLElement[]) => void;
  /** Während eines programmatischen Sprungs keine Meldungen (sonst wählt er jeden überflogenen Punkt). */
  setPaused: (paused: boolean) => void;
  /** Vom Editor gesetzter aktiver Punkt (Sprung), damit der Spy ihn nicht erneut meldet. */
  setCurrent: (id: string | null) => void;
  destroy: () => void;
};

export function createSectionSpy(
  root: HTMLElement,
  idOf: (section: Element) => string | null,
  onActive: (id: string) => void
): SectionSpy | null {
  if (typeof IntersectionObserver === "undefined") return null;
  const visible = new Set<Element>();
  let order: HTMLElement[] = [];
  let paused = false;
  let last: string | null = null;

  const pick = () => {
    if (paused) return;
    const hit = order.find((section) => visible.has(section));
    // Ganz am Anfang des Dokuments: der erste Punkt, auch wenn ein kurzer Folgepunkt schon ins
    // obere Drittel reicht
    const atStart = root.scrollTop <= 1 && order[0] ? order[0] : null;
    const chosen = atStart ?? hit;
    const id = chosen ? idOf(chosen) : null;
    if (!id || id === last) return;
    last = id;
    onActive(id);
  };

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) visible.add(entry.target);
        else visible.delete(entry.target);
      }
      pick();
    },
    { root, rootMargin: SPY_ROOT_MARGIN }
  );

  return {
    observe(sections) {
      observer.disconnect();
      visible.clear();
      order = sections;
      sections.forEach((section) => observer.observe(section));
    },
    setCurrent(id) {
      last = id;
    },
    setPaused(next) {
      // Nach einem Sprung bleibt der angesprungene Punkt aktiv, bis wieder gescrollt wird: am
      // Ende des Dokuments erreichte der Kopf eines kurzen letzten Punkts das obere Drittel nie.
      paused = next;
    },
    destroy() {
      observer.disconnect();
      visible.clear();
    },
  };
}
