import { getTranslations } from "next-intl/server";

export default async function NotFound() {
  const t = await getTranslations("abgabebox.notFound");
  return (
    <div className="card">
      <h1>{t("title")}</h1>
      <p className="muted">{t("hint")}</p>
    </div>
  );
}
