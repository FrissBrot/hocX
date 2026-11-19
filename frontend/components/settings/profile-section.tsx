import type { ReactNode } from "react";

/**
 * Abschnitt einer Einstellungsseite (Profil, Design «hocX Einstellungen»): Karte mit Titel und
 * einem Satz Beschreibung, darunter der Inhalt. `id` ist die Sprungmarke der globalen Suche
 * (lib/search/setting-entries.ts).
 */
export function ProfileSection({ id, title, description, children }: { id: string; title: string; description?: string; children: ReactNode }) {
  return (
    <section className="card settings-anchor tenant-section" id={id} aria-labelledby={`${id}-title`}>
      <div className="tenant-section-head">
        <h2 className="tenant-section-title" id={`${id}-title`}>{title}</h2>
        {description ? <p className="muted tenant-section-description">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}
