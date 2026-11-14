"use client";

import Link from "next/link";
import type { Route } from "next";
import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { StatusBanner } from "@/components/ui/status-banner";
import { formatDate, formatDateTime } from "@/lib/utils/format";
import type { PublicLinkItem } from "@/types/api";

type Group = "all" | "files" | "submissions" | "calendar" | "accounts" | "partners" | "other";

/** Gruppe einer Link-Art fürs Filtern. Unbekannte (künftige) Arten landen unter «Weitere». */
export function linkGroup(kind: string): Exclude<Group, "all"> {
  if (kind.startsWith("share_")) return "files";
  if (kind.startsWith("submission_")) return "submissions";
  if (kind.startsWith("calendar_")) return "calendar";
  if (kind.startsWith("account_")) return "accounts";
  if (kind.startsWith("album_")) return "partners";
  return "other";
}

/**
 * Zugangslinks (Mandant-Einstellungen): alles, worüber jemand ohne Anmeldung an Daten des Vereins
 * kommt - mit Grund, Ablauf und dem Ort, an dem man den Link verwaltet. Die Liste kommt aus dem
 * Register app/public_links im Backend; neue Link-Arten erscheinen dort automatisch (unbekannte
 * Arten zeigt die Tabelle mit ihrem Schlüssel unter «Weitere»).
 */
export function PublicLinksOverview({ links, mobile = false }: { links: PublicLinkItem[]; mobile?: boolean }) {
  const t = useTranslations("tenantSettings.publicLinks");
  const locale = useLocale();
  const [group, setGroup] = useState<Group>("all");

  const counts = useMemo(() => {
    const result: Record<string, number> = {};
    for (const link of links) result[linkGroup(link.kind)] = (result[linkGroup(link.kind)] ?? 0) + 1;
    return result;
  }, [links]);
  const groups: Group[] = ["all", "files", "submissions", "calendar", "accounts", "partners", ...(counts.other ? (["other"] as Group[]) : [])];
  const visible = group === "all" ? links : links.filter((link) => linkGroup(link.kind) === group);
  const neverExpiring = links.filter((link) => link.expiry === "never").length;

  function kindLabel(kind: string) {
    return t.has(`kind.${kind}`) ? t(`kind.${kind}`) : kind;
  }

  function reason(link: PublicLinkItem) {
    return t.has(`reason.${link.kind}`) ? t(`reason.${link.kind}`, link.params) : t("reason.unknown");
  }

  function expiry(link: PublicLinkItem) {
    if (link.expiry === "date") return link.expires_at ? t("expiry.date", { date: formatDate(link.expires_at) }) : t("expiry.never");
    if (link.expiry === "single_use") return link.expires_at ? t("expiry.singleUseUntil", { date: formatDate(link.expires_at) }) : t("expiry.singleUse");
    if (link.expiry === "window") return t("expiry.window");
    return t("expiry.never");
  }

  return (
    <div className="section-stack">
      <p className="muted">{t("intro")}</p>
      {neverExpiring > 0 ? <StatusBanner tone="neutral" message={t("neverExpiringHint", { count: neverExpiring })} /> : null}
      <FilterTabs
        options={groups.map((value) => ({ value, label: t(`group.${value}`), count: value === "all" ? links.length : counts[value] ?? 0 }))}
        value={group}
        onChange={setGroup}
        variant={mobile ? "chips" : "segmented"}
      />
      {mobile ? (
        <div className="public-links-cards">
          {visible.length === 0 ? <p className="muted">{links.length === 0 ? t("empty") : t("emptyFilter")}</p> : null}
          {visible.map((link) => (
            <div key={`${link.kind}:${link.id}`} className="mobile-card public-links-card">
              <div className="public-links-card-head">
                <span className="public-links-label">{link.label || "—"}</span>
                <Badge variant={link.expiry === "never" ? "warning" : "neutral"}>{kindLabel(link.kind)}</Badge>
              </div>
              <div className="muted public-links-reason">{reason(link)}</div>
              <div className="public-links-reason">{expiry(link)}{link.created_by ? ` · ${t("createdBy", { name: link.created_by })}` : ""}</div>
              {link.manage_href ? <Link className="button-secondary button-ghost public-links-card-action" href={link.manage_href as Route}>{t("manage")}</Link> : null}
            </div>
          ))}
        </div>
      ) : (
      <DataTable
        columns={[t("col.kind"), t("col.link"), t("col.created"), t("col.expiry"), t("col.lastUsed"), t("col.manage")]}
        emptyMessage={links.length === 0 ? t("empty") : t("emptyFilter")}
      >
        {visible.map((link) => (
          <tr key={`${link.kind}:${link.id}`}>
            <td><Badge variant={link.expiry === "never" ? "warning" : "neutral"}>{kindLabel(link.kind)}</Badge></td>
            <td>
              <div className="public-links-label">{link.label || "—"}</div>
              <div className="muted public-links-reason">{reason(link)}</div>
            </td>
            <td>
              {link.created_at ? formatDate(link.created_at) : "—"}
              {link.created_by ? <div className="muted public-links-reason">{t("createdBy", { name: link.created_by })}</div> : null}
            </td>
            <td>{expiry(link)}</td>
            <td>{link.last_used_at ? formatDateTime(link.last_used_at, locale) : <span className="muted">{t("notTracked")}</span>}</td>
            <td>
              {link.manage_href ? (
                <Link className="button-secondary button-ghost" href={link.manage_href as Route}>{t("manage")}</Link>
              ) : (
                <span className="muted">{t(`manageElsewhere.${linkGroup(link.kind)}`)}</span>
              )}
            </td>
          </tr>
        ))}
      </DataTable>
      )}
    </div>
  );
}
