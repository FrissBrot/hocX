"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { getRuntimeConfig } from "@/lib/runtime-config";
import { getReleaseUrl } from "@/lib/release-url";
import { Badge } from "./badge";

export function VersionNotice({ className = "" }: { className?: string }) {
  const t = useTranslations("common");
  const [config, setConfig] = useState<ReturnType<typeof getRuntimeConfig> | null>(null);
  useEffect(() => { setConfig(getRuntimeConfig()); }, []);
  if (!config) return null;
  const label = config.environment === "development"
    ? t("build.development", { branch: config.branch || t("build.unknown"), commit: config.commit || t("build.unknown") })
    : config.environment === "test"
      ? t("build.test", { image: config.version })
      : t("build.production", { version: config.version });
  return (
    <span className={["version-notice", className].filter(Boolean).join(" ")}>
      {config.environment === "development" || config.environment === "test" ? (
        <Badge variant={config.environment === "development" ? "warning" : "info"} className="version-environment">
          {t(config.environment === "development" ? "build.developmentBadge" : "build.testBadge")}
        </Badge>
      ) : <span className="version-production-dot" aria-hidden="true" />}
      {config.environment === "production" ? (
        <a href={getReleaseUrl(config.version)} target="_blank" rel="noopener noreferrer" title={t("build.releaseLinkTitle")}>{label}</a>
      ) : <span className="version-label" title={label}>{label}</span>}
    </span>
  );
}
