/** Dekorative Bergsilhouette; kein Fortschritt oder Höhenprofil der berechneten Route. */
export function HikingTourLoadingLandscape() {
  return (
    <span className="wanderplaner-loading-landscape" aria-hidden="true">
      <svg viewBox="0 0 480 48" preserveAspectRatio="none" focusable="false">
        {[0, 240].map((offset) => (
          <g key={offset} transform={`translate(${offset} 0)`}>
            <path className="wanderplaner-loading-landscape-area" d="M0 34 L18 28 L34 32 L58 10 L76 24 L92 18 L118 36 L142 22 L162 28 L188 6 L210 25 L224 20 L240 34 V48 H0 Z" />
            <path className="wanderplaner-loading-landscape-ridge" d="M0 34 L18 28 L34 32 L58 10 L76 24 L92 18 L118 36 L142 22 L162 28 L188 6 L210 25 L224 20 L240 34" />
          </g>
        ))}
      </svg>
    </span>
  );
}
