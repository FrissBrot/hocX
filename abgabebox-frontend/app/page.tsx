// Kein Einstieg ohne Link: die Abgabebox ist nur ueber den (zufaelligen) Abgabe-Link
// <domain>/<token> erreichbar, den der Verein weitergibt. Die Startseite verrät bewusst weder
// Mandanten noch Abgaben.
export default function RootPage() {
  return (
    <div className="card">
      <h1>Abgabebox</h1>
      <p className="muted">Bitte den vollständigen Abgabe-Link verwenden, den du vom Verein erhalten hast.</p>
    </div>
  );
}
