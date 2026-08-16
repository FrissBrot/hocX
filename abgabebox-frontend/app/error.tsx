"use client";

// Audit A6, 2026-08-16: without this, an unhandled fetch/network error (e.g. the backend
// being restarted/unreachable) fell through to Next.js' generic English default error page -
// a jarring break from the otherwise fully German-language Abgabebox, for a real failure
// mode (backend restart mid-deploy) that will actually happen from time to time.
export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="card">
      <h1>Etwas ist schiefgelaufen</h1>
      <p className="muted">
        Die Seite konnte nicht geladen werden. Das kann an einer kurzzeitigen Störung liegen -
        bitte versuche es gleich nochmal.
      </p>
      <button type="button" onClick={reset}>
        Erneut versuchen
      </button>
    </div>
  );
}
