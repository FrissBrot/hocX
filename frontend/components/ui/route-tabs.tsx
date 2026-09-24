import Link from "next/link";
import type { Route } from "next";

export type RouteTab = { href: string; label: string };

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
  return (
    <div className={isPill ? "filter-tabs" : "tabs-list route-tabs"} role="tablist">
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
            className={isActive ? `${baseClass} ${activeClass}` : baseClass}
          >
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}
