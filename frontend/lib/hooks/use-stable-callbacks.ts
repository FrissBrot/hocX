import { useLayoutEffect, useRef, useState } from "react";

type AnyFunction = (...args: never[]) => unknown;

/**
 * Liefert für ein Objekt aus Funktionen gleichnamige Hüllen mit stabiler Identität, die immer
 * die zuletzt übergebene Funktion aufrufen. So können Kinder memoisiert werden (React.memo),
 * obwohl die Handler bei jedem Render neu entstehen und auf aktuellen Zustand zugreifen.
 * Die Schlüssel müssen über die Lebensdauer der Komponente gleich bleiben.
 * Nur für Ereignis-Handler gedacht, nicht für Funktionen, die während des Renderns laufen.
 */
export function useStableCallbacks<T extends Record<string, AnyFunction>>(callbacks: T): T {
  const latest = useRef(callbacks);
  useLayoutEffect(() => {
    latest.current = callbacks;
  });
  const [stable] = useState(() => {
    const wrappers = {} as Record<string, AnyFunction>;
    for (const key of Object.keys(callbacks)) {
      wrappers[key] = ((...args: never[]) => latest.current[key](...args)) as AnyFunction;
    }
    return wrappers as T;
  });
  return stable;
}
