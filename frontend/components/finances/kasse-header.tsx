"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { RouteTabs } from "@/components/ui/route-tabs";
import { financeTabs } from "@/components/ui/section-tabs";
import { DocsLink } from "@/components/ui/help-popover";

type Props = {
  /** Aktiver Reiter: /finances = «Konten», /fines = «Bussen». */
  active: "/finances" | "/fines";
  /** Reiter «Konten» nur mit finances.read (die Route /finances prüft es selbst). */
  showAccountsTab: boolean;
  /** Zähler am Reiter «Bussen»: Anzahl offener Bussen (null = unbekannt, kein Abzeichen). */
  openCount: number | null;
  lead: ReactNode;
  /** Zusatz hinter dem Titel, z. B. Hilfe-Popover. */
  titleExtra?: ReactNode;
  /** Aktionen rechts im Kopf, z. B. «+ Busse». */
  actions?: ReactNode;
};

/**
 * Gemeinsamer Kopf der Seite «Kasse» (Design «Kasse und Bussen v2»): Titel, Lead je Reiter mit
 * Link zur Hilfe und die Reiter «Konten» / «Bussen». Die Reiter sind weiterhin eigene Routen
 * (RouteTabs), damit bestehende Links, Suche, Seitenleiste und Rechteprüfung unverändert bleiben.
 */
export function KasseHeader({ active, showAccountsTab, openCount, lead, titleExtra, actions }: Props) {
  const t = useTranslations("finances");
  const tNav = useTranslations("nav");
  const tabs = financeTabs(tNav)
    .filter((tab) => showAccountsTab || tab.href !== "/finances")
    .map((tab) => (tab.href === "/fines" ? { ...tab, count: openCount } : tab));
  return (
    <div className="kasse-head">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("kasse.title")}{titleExtra ? <> {titleExtra}</> : null}</h1>
          <p className="muted kasse-lead">
            {lead} <DocsLink page="finanzen">{t("kasse.helpLink")}</DocsLink>
          </p>
        </div>
        {actions ? <div className="kasse-head-actions">{actions}</div> : null}
      </div>
      <RouteTabs tabs={tabs} activeHref={active} />
    </div>
  );
}
