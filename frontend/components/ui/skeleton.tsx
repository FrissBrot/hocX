/** Platzhalter während des Ladens. Für Screenreader unsichtbar - der Ladezustand wird über aria-busy des Bereichs gemeldet. */
export function Skeleton({ variant = "line", className }: { variant?: "line" | "block" | "tile"; className?: string }) {
  return <span aria-hidden="true" className={`skeleton skeleton-${variant}${className ? ` ${className}` : ""}`} />;
}
