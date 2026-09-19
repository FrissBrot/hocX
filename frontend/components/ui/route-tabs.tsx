import Link from "next/link";
import type { Route } from "next";

export type RouteTab = { href: string; label: string };

// Tab strip whose tabs are separate routes (each keeps its own URL, page and access check).
// Pages pass only the tabs the current role may open - the strip does no filtering itself.
export function RouteTabs({ tabs, activeHref }: { tabs: RouteTab[]; activeHref: string }) {
  if (tabs.length < 2) {
    return null;
  }
  return (
    <div className="tabs-list route-tabs" role="tablist">
      {tabs.map((tab) => {
        const isActive = tab.href === activeHref;
        return (
          <Link
            key={tab.href}
            href={tab.href as Route}
            role="tab"
            aria-selected={isActive}
            className={isActive ? "tabs-trigger tabs-trigger-active" : "tabs-trigger"}
          >
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}
