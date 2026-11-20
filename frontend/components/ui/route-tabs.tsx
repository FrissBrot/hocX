"use client";

import Link from "next/link";
import type { Route } from "next";

import { rovingKeyDown } from "@/lib/a11y/roving";

export type RouteTab = { href: string; label: string; /** Zählerabzeichen hinter dem Titel (0/leer = ohne), wie `Tabs`. */ count?: number | null };

// Tab strip whose tabs are separate routes (each keeps its own URL, page and access check).
// Pages pass only the tabs the current role may open - the strip does no filtering itself.
// `variant="pill"` reuses the FilterTabs look (rounded segmented control) for sections whose
// design calls for that instead of the default underline tabs.
export function RouteTabs({
  tabs,
  activeHref,
  variant = "underline",
}: {
  tabs: RouteTab[];
  activeHref: string;
  variant?: "underline" | "pill";
}) {
  if (tabs.length < 2) {
    return null;
  }
  const isPill = variant === "pill";
  const focusHref = tabs.some((tab) => tab.href === activeHref) ? activeHref : tabs[0]?.href;
  return (
    // Tabs als Links (manuelle Aktivierung): Pfeile verschieben nur den Fokus, Enter öffnet die Route
    <div
      className={isPill ? "filter-tabs" : "tabs-list route-tabs"}
      role="tablist"
      onKeyDown={(event) => rovingKeyDown(event, { itemSelector: '[role="tab"]' })}
    >
      {tabs.map((tab) => {
        const isActive = tab.href === activeHref;
        const activeClass = isPill ? "filter-tabs-option-active" : "tabs-trigger-active";
        const baseClass = isPill ? "filter-tabs-option" : "tabs-trigger";
        return (
          <Link
            key={tab.href}
            href={tab.href as Route}
            role="tab"
            aria-selected={isActive}
            aria-current={isActive ? "page" : undefined}
            tabIndex={tab.href === focusHref ? 0 : -1}
            className={isActive ? `${baseClass} ${activeClass}` : baseClass}
          >
            {tab.label}
            {tab.count ? <span className="tabs-count">{tab.count}</span> : null}
          </Link>
        );
      })}
    </div>
  );
}
