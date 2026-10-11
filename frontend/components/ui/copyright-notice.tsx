"use client";

import { useTranslations } from "next-intl";
import { VersionNotice } from "./version-notice";

export function CopyrightNotice({ className = "" }: { className?: string }) {
  const t = useTranslations("common");
  const classes = ["copyright-notice", className].filter(Boolean).join(" ");

  return <p className={classes}><VersionNotice />{t("copyright", { year: new Date().getFullYear() })}</p>;
}
