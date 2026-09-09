"use client";

export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="login-frame">
      <section className="login-panel">
        <div className="login-brand">
          <div className="login-avatar login-avatar-fallback">
            <span>hX</span>
          </div>
          <div className="eyebrow">hocX</div>
        </div>
        <div className="login-heading">
          <h1>Verbindung unterbrochen</h1>
          <p className="login-subtitle">Der Server ist momentan nicht erreichbar. Bereits bestätigte Daten bleiben erhalten; prüfe nach dem erneuten Verbinden den Speicherstatus offener Änderungen.</p>
        </div>
        <button type="button" className="button-inline login-submit" onClick={() => reset()}>
          Erneut versuchen
        </button>
      </section>
    </main>
  );
}
