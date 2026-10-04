type Props = { points?: [number, number][] };

export function HikingTourElevationPreview({ points = [] }: Props) {
  if (points.length < 2) return <span className="muted" aria-hidden="true">–</span>;
  const distances = points.map(([distance]) => distance);
  const elevations = points.map(([, elevation]) => elevation);
  const minDistance = Math.min(...distances);
  const distanceSpan = Math.max(...distances) - minDistance;
  const minElevation = Math.min(...elevations);
  const elevationSpan = Math.max(...elevations) - minElevation;
  const coordinates = points.map(([distance, elevation]) => {
    const x = 2 + (distanceSpan ? (distance - minDistance) / distanceSpan : 0) * 156;
    const y = elevationSpan ? 38 - (elevation - minElevation) / elevationSpan * 30 : 23;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  return (
    <svg viewBox="0 0 160 44" className="wanderplaner-elevation-preview" aria-hidden="true" focusable="false">
      <path d={`M2,42 L${coordinates.join(" L")} L158,42 Z`} className="wanderplaner-elevation-preview-area" />
      <polyline points={coordinates.join(" ")} className="wanderplaner-elevation-preview-line" />
    </svg>
  );
}
