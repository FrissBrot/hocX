"use client";

import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

// Texte der Markenfläche: Abgabe-Ablauf oder Echtheitsprüfung (/verify), je nach Route.
export function isVerifyPath(pathname: string | null): boolean {
  return (pathname ?? "").split("/").filter(Boolean)[0] === "verify";
}

export function BrandSubtitle() {
  const t = useTranslations("abgabebox");
  return <>{isVerifyPath(usePathname()) ? t("verify.brand.subtitle") : t("brand.subtitle")}</>;
}

export function BrandIntro() {
  const t = useTranslations("abgabebox");
  const verify = isVerifyPath(usePathname());
  return (
    <div className="box-brand-intro">
      <h2>{verify ? t("verify.brand.headline") : t("brand.headline")}</h2>
      <p>{verify ? t("verify.brand.lead") : t("brand.lead")}</p>
    </div>
  );
}

export function BrandNote() {
  const t = useTranslations("abgabebox");
  return <span>{isVerifyPath(usePathname()) ? t("verify.brand.privacyNote") : t("brand.securityNote")}</span>;
}
