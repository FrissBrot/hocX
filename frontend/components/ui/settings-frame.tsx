"use client";

import Link from "next/link";
import type { Route } from "next";
import type { ReactNode, SVGProps } from "react";
import { useTranslations } from "next-intl";

import { isNavLinkActive, SETTINGS_HREF, type SettingsGroup } from "@/components/ui/app-shell-nav";
import { NavIcon } from "@/components/ui/nav-icons";

/** Zahnrad für den Knopf «Einstellungen» (Seitenleiste) und den Querverweis in der Kopfzeile. */
export function SettingsIcon(props: Omit<SVGProps<SVGSVGElement>, "viewBox" | "fill">) {
  return (
    <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

// Editoren (eine Vorlage, ein Import, das Erscheinungsbild mit Live-Vorschau in drei Spalten)
// brauchen die ganze Breite: dort bleibt nur die Kopfzeile
// «Einstellungen / <Seite>», die Unternavigation entfällt.
const FRAMELESS = [/^\/documents\/brand/, /^\/templates\/[^/]+/, /^\/documents\/templates\//, /^\/tools\/import\/[^/]+/, /^\/tools\/word-import/];

export function usesSettingsFrame(pathname: string): boolean {
  return !FRAMELESS.some((pattern) => pattern.test(pathname));
}

/**
 * Gemeinsamer Rahmen aller Einstellungsseiten (Design «hocX Einstellungen»): links die
 * Unternavigation (Übersicht + Gruppen), rechts der unveränderte Inhalt der Seite. Kopf-Breadcrumb
 * und Chip «← Zurück zu <Bereich>» kommen aus der Kopfzeile der App-Shell. Nur Desktop - auf dem
 * Handy führt «Mehr › Einstellungen» zur Übersicht.
 *
 * Die App-Shell rendert den Rahmen für jede Seite, ohne `enabled` nur als zwei unsichtbare Hüllen
 * (`.shell-slot`, display: contents): so liegt der Seiteninhalt immer an derselben Stelle im
 * React-Baum und wird beim Wechsel Desktop/Mobil nicht neu gemountet.
 */
export function SettingsFrame({ groups, pathname, enabled = true, children }: { groups: SettingsGroup[]; pathname: string; enabled?: boolean; children: ReactNode }) {
  const t = useTranslations("nav");
  const tSettings = useTranslations("settings.hub");
  return (
    <div className={enabled ? "settings-frame" : "shell-slot"}>
      {enabled ? (
        <nav className="settings-subnav" aria-label={t("groups.settings")}>
          <Link
            href={SETTINGS_HREF as Route}
            className={pathname === SETTINGS_HREF ? "settings-subnav-link settings-subnav-link-active" : "settings-subnav-link"}
            aria-current={pathname === SETTINGS_HREF ? "page" : undefined}
          >
            <NavIcon name="dashboard" className="settings-subnav-icon" />
            <span>{tSettings("overview")}</span>
          </Link>
          {groups.map((group) => (
            <div className="settings-subnav-group" key={group.titleKey}>
              <div className="settings-subnav-title">{t(group.titleKey)}</div>
              {group.links.map((link) => {
                const active = isNavLinkActive(link, pathname);
                return (
                  <Link
                    key={link.href}
                    href={link.href as Route}
                    className={active ? "settings-subnav-link settings-subnav-link-active" : "settings-subnav-link"}
                    aria-current={active ? "page" : undefined}
                  >
                    <NavIcon name={link.icon} className="settings-subnav-icon" />
                    <span>{t(link.labelKey)}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
      ) : null}
      <div className={enabled ? "settings-frame-content" : "shell-slot shell-page"}>{children}</div>
    </div>
  );
}
