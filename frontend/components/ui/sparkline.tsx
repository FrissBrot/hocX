/**
 * Kleiner Verlauf als SVG (ohne Diagramm-Bibliothek). Farbe über die Klasse (Tokens), Beschriftung
 * über `label` (role="img"). Für exakte Werte gehört eine Tabellenalternative daneben.
 */
export function Sparkline({
  values,
  label,
  tone = "accent",
  width = 96,
  height = 28,
}: {
  values: number[];
  label: string;
  tone?: "accent" | "success" | "warning" | "danger";
  width?: number;
  height?: number;
}) {
  if (values.length === 0) return null;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  const points = values
    .map((value, index) => {
      const x = values.length > 1 ? index * step : width / 2;
      const y = height - 2 - ((value - min) / span) * (height - 4);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg className={`sparkline sparkline-${tone}`} width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      <polyline points={points} fill="none" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
