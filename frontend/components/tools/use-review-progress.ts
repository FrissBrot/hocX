import { useEffect, useRef } from "react";

/**
 * Merkt sich, ob seit dem letzten geladenen Analyse-Stand echte Prüfarbeit passiert ist (Word-Import:
 * «Neu analysieren» fragt nur dann nach). Vergleicht die beobachteten Werte mit den Referenzen des
 * geladenen Stands, statt Effektläufe zu zählen: React StrictMode und Fast Refresh lassen Effekte im
 * Dev-Server ohne Änderung erneut laufen - ein Zähl-/Flag-Ansatz hielt den frisch geladenen Stand
 * dann für Fortschritt und fragte grundlos nach.
 */
export function useReviewProgress(values: readonly unknown[]) {
  const baselineRef = useRef<readonly unknown[] | null>(null);
  const progressRef = useRef(false);

  useEffect(() => {
    const baseline = baselineRef.current;
    if (baseline && values.some((value, index) => !Object.is(value, baseline[index]))) {
      progressRef.current = true;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, values);

  return {
    /** Gibt es Änderungen gegenüber dem geladenen Stand (oder einen wiederhergestellten Entwurf)? */
    hasProgress: () => progressRef.current,
    /** Neuer Ausgangsstand: genau die Werte, die gleich in den State geschrieben werden. */
    reset: (baseline: readonly unknown[], hasProgress: boolean) => {
      baselineRef.current = baseline;
      progressRef.current = hasProgress;
    },
  };
}
