"use client";

import Link from "next/link";
import type { Route } from "next";
import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { useOpenMore } from "@/components/mobile/mobile-shell";
import { MobileSubHeader } from "@/components/mobile/mobile-ui";
import type { SettingsGroup } from "@/components/ui/app-shell-nav";
import { NavIcon } from "@/components/ui/nav-icons";
import { SearchInput } from "@/components/ui/search-input";
import { matchScore } from "@/lib/search/match";

export type SettingsCardStatus = { text: string; tone: "neutral" | "success" | "warning" };
export type SettingsAttentionItem = { id: string; title: string; hint: string; href: string };

type Props = {
  groups: SettingsGroup[];
  tenantName: string;
  /** Statuszeile je Karte (href → Text), nur wo sie billig aus Session/API ableitbar ist. */
  statuses: Record<string, SettingsCardStatus>;
  attention: SettingsAttentionItem[];
  mobile?: boolean;
};

/**
 * Übersicht aller Einstellungen (/settings, Design «hocX Einstellungen»): Suchfeld, «Braucht
 * Aufmerksamkeit» und je Gruppe ein Kartenraster. Die Karten kommen aus buildSettingsNav - es
 * erscheint nur, was die Person öffnen darf.
 */
export function SettingsOverview({ groups, tenantName, statuses, attention, mobile = false }: Props) {
  const t = useTranslations("settings.hub");
  const tNav = useTranslations("nav");
  const tMobile = useTranslations("mobile");
  const tSearch = useTranslations("search");
  const openMore = useOpenMore();
  const [query, setQuery] = useState("");

  const visibleGroups = useMemo(() => {
    const needle = query.trim();
    if (!needle) return groups;
    return groups
      .map((group) => ({
        ...group,
        // Wie die globale Suche: Titel, Gruppe, Beschreibung und die Suchbegriffe des Eintrags
        // (search.keywords.<labelKey> bzw. .<pfad>, auch der Unterseiten - z. B. «DSGVO» findet
        // Datenschutz, «Löschfristen» über die Aufbewahrung ebenfalls)
        links: group.links.filter((link) => {
          const keywordKeys = [link.labelKey, ...[link.href, ...(link.match ?? [])].map((href) => href.split("/").filter(Boolean).join("-"))]
            .map((key) => `keywords.${key}`)
            .filter((key) => tSearch.has(key));
          const keywords = [t(`cards.${link.labelKey}.description`), ...keywordKeys.map((key) => tSearch(key))].join(" ");
          return matchScore({ label: tNav(link.labelKey), sublabel: tNav(group.titleKey), keywords }, needle) > 0;
        }),
      }))
      .filter((group) => group.links.length > 0);
  }, [groups, query, t, tNav, tSearch]);

  const search = (
    <SearchInput
      className="settings-hub-search"
      value={query}
      onChange={setQuery}
      placeholder={t("searchPlaceholder")}
      aria-label={t("searchLabel")}
    />
  );

  const body = (
    <>
      {attention.length > 0 && !query.trim() ? (
        <section className="settings-hub-attention" aria-labelledby="settings-hub-attention-title">
          <h2 id="settings-hub-attention-title" className="settings-hub-group-title">{t("attentionTitle")}</h2>
          {attention.map((item) => (
            <div key={item.id} className="settings-hub-attention-row">
              <span className="settings-hub-attention-dot" aria-hidden="true" />
              <div className="settings-hub-attention-text">
                <strong>{item.title}</strong>
                <span className="muted">{item.hint}</span>
              </div>
              <Link href={item.href as Route} className="button-secondary">{t("review")}</Link>
            </div>
          ))}
        </section>
      ) : null}

      {visibleGroups.length === 0 ? <p className="muted">{t("noResults")}</p> : null}

      {visibleGroups.map((group) => (
        <section key={group.titleKey} className="settings-hub-group" aria-labelledby={`settings-hub-${group.titleKey}`}>
          <h2 id={`settings-hub-${group.titleKey}`} className="settings-hub-group-title">{tNav(group.titleKey)}</h2>
          <div className="settings-hub-grid">
            {group.links.map((link) => {
              const status = statuses[link.href];
              return (
                <Link key={link.href} href={link.href as Route} className="settings-hub-card">
                  <span className="settings-hub-card-icon" aria-hidden="true">
                    <NavIcon name={link.icon} />
                  </span>
                  <span className="settings-hub-card-text">
                    <span className="settings-hub-card-title">{tNav(link.labelKey)}</span>
                    <span className="settings-hub-card-description">{t(`cards.${link.labelKey}.description`)}</span>
                    {status ? (
                      <span className={`settings-hub-card-status settings-hub-card-status-${status.tone}`}>{status.text}</span>
                    ) : null}
                  </span>
                </Link>
              );
            })}
          </div>
        </section>
      ))}
    </>
  );

  if (mobile) {
    return (
      <div className="mobile-page">
        <MobileSubHeader title={t("title")} backLabel={tMobile("tabs.more")} onBack={openMore} />
        <div className="mobile-section settings-hub settings-hub-mobile">
          {search}
          {body}
        </div>
      </div>
    );
  }

  return (
    <section className="panel settings-hub">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("description", { tenant: tenantName })}</p>
        </div>
      </div>
      {search}
      {body}
    </section>
  );
}
