"use client";

import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";

import { RouteTabs, type RouteTab } from "@/components/ui/route-tabs";

// Unterseiten des Sicherheitsbereichs (Plan §2 D) - eigene Routen, damit jede Ansicht verlinkbar ist.
export const SECURITY_SECTIONS = ["overview", "incidents", "events", "blocks", "alerts", "audit", "policy"] as const;
export type SecuritySection = (typeof SECURITY_SECTIONS)[number];

export function securityHref(section: SecuritySection): string {
  return section === "overview" ? "/admin/security" : `/admin/security/${section}`;
}

export function SecurityTabs() {
  const t = useTranslations("adminSecurity");
  const pathname = usePathname();
  const tabs: RouteTab[] = SECURITY_SECTIONS.map((section) => ({ href: securityHref(section), label: t(`tabs.${section}`) }));
  return (
    <nav aria-label={t("tabsLabel")}>
      <RouteTabs tabs={tabs} activeHref={pathname ?? "/admin/security"} />
    </nav>
  );
}
