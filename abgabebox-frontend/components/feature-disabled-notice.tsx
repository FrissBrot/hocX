// Hinweis «Abgabebox für diese Organisation nicht verfügbar» - gleich auf der Abgabenliste,
// der Dokumentauswahl und der Upload-Seite. Texte kommen von der Seite (Server-Übersetzung).
export function FeatureDisabledNotice({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="card">
      <h1>{title}</h1>
      <p className="muted muted-flush">{hint}</p>
    </div>
  );
}
