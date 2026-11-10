"use client";

import Link from "next/link";
import type { Route } from "next";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { MobileIcon } from "@/components/mobile/mobile-icons";
import { browserApiFetch } from "@/lib/api/client";
import { CONNECTIONS_HREF } from "@/lib/calendar-feeds";
import type { CalendarFeed, CalendarFeedKind } from "@/types/api";

/** Dezenter Hinweis auf den Termine-/Todos-Seiten, dass sich die Liste mit Apple/Google Kalender
 * verknuepfen laesst - bzw. ein kurzer Status, wenn das schon passiert ist. Best effort: ohne
 * Antwort vom Backend erscheint einfach nichts, die Seite selbst haengt nie daran. */
export function CalendarLinkHint({ kind, mobile = false }: { kind: CalendarFeedKind; mobile?: boolean }) {
  const t = useTranslations("connections.hint");
  const [linked, setLinked] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    browserApiFetch<CalendarFeed[]>("/api/calendar-feeds")
      .then((feeds) => {
        if (!cancelled) setLinked((feeds ?? []).some((feed) => feed.kind === kind && feed.status === "active"));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [kind]);

  if (linked === null) return null;

  const className = `calendar-link-hint${mobile ? " calendar-link-hint-mobile" : ""}${linked ? " calendar-link-hint-linked" : ""}`;

  if (linked) {
    return (
      <Link href={CONNECTIONS_HREF as Route} className={className}>
        <MobileIcon name="check" size={14} strokeWidth={2.4} className="calendar-link-hint-icon" />
        <span>{t("linked")}</span>
        <span className="calendar-link-hint-action">{t("manage")}</span>
      </Link>
    );
  }

  return (
    <Link href={CONNECTIONS_HREF as Route} className={className}>
      <MobileIcon name="calendar" size={14} strokeWidth={2.2} className="calendar-link-hint-icon" />
      <span>{t(kind)}</span>
      <span className="calendar-link-hint-action">
        {t("action")}
        <MobileIcon name="chevronRight" size={12} strokeWidth={2.4} />
      </span>
    </Link>
  );
}
