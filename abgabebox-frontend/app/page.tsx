import { getTranslations } from "next-intl/server";

// Kein Einstieg ohne Link: die Abgabebox ist nur ueber den (zufaelligen) Abgabe-Link
// <domain>/<token> erreichbar, den der Verein weitergibt. Die Startseite verrät bewusst weder
// Mandanten noch Abgaben.
export default async function RootPage() {
  const t = await getTranslations("abgabebox.home");
  return (
    <div className="card">
      <h1>{t("title")}</h1>
      <p className="muted">{t("hint")}</p>
    </div>
  );
}
