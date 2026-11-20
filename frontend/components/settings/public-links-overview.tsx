"use client";

import Link from "next/link";
import type { Route } from "next";
import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Tabs } from "@/components/ui/tabs";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate, formatDateTime } from "@/lib/utils/format";
import type { PartnerHistoryEntry, PublicLinkItem } from "@/types/api";

type Group = "all" | "files" | "submissions" | "calendar" | "accounts" | "partners" | "other";

/**
 * Gruppe einer Link-Art fürs Filtern. Partner-Links auf eigene Alben gehören zu den
 * Partner-Organisationen (dort steht auch ihr Verlauf). Unbekannte (künftige) Arten landen unter «Weitere».
 */
export function linkGroup(kind: string): Exclude<Group, "all"> {
  if (kind === "share_album_partner" || kind.startsWith("album_")) return "partners";
  if (kind.startsWith("share_")) return "files";
  if (kind.startsWith("submission_")) return "submissions";
  if (kind.startsWith("calendar_")) return "calendar";
  if (kind.startsWith("account_")) return "accounts";
  return "other";
}

/** Zeilen einer Partner-Organisation (Album geteilt, Partner-Link): Ziel von «Verlauf». */
function partnerOf(link: PublicLinkItem): string | null {
  if (linkGroup(link.kind) !== "partners") return null;
  const partner = link.params.partner;
  return typeof partner === "string" && partner ? partner : null;
}

// Direkt hier widerrufbar (Plan «Berechtigungen», Phase 6): eigene Freigabelinks für Dateien/Alben
// über DELETE /api/share-links/{id}. Andere Arten verwalten ihre Seiten (Abgabe-Links hängen an
// Aufträgen, Einladungen an Personen, Partner-Links verwaltet die Partner-Organisation).
const REVOCABLE = new Set(["share_files", "share_album"]);

/** Nur Tag und Monat («17.11.») - für «genutzt …» in der Zeile. */
function dayMonth(input: string): string {
  return formatDate(input).slice(0, 6);
}

/**
 * Zugangslinks (Mandant-Einstellungen): alles, worüber jemand ohne Anmeldung an Daten des Vereins
 * kommt - mit Grund, Ablauf und dem Ort, an dem man den Link verwaltet. Die Liste kommt aus dem
 * Register app/public_links im Backend; neue Link-Arten erscheinen dort automatisch (unbekannte
 * Arten zeigt die Liste mit ihrem Schlüssel unter «Weitere»). Im Reiter Partner-Organisationen
 * zusätzlich der Verlauf der Partner (GET /api/public-links/partner-history).
 */
export function PublicLinksOverview({
  links: initialLinks,
  history = [],
  mobile = false,
  canRevoke = true,
  canOpenActivity = true,
}: {
  links: PublicLinkItem[];
  history?: PartnerHistoryEntry[];
  mobile?: boolean;
  /** sharing.public: nur dann ist Widerrufen möglich (Prüfung im Backend bleibt massgebend) */
  canRevoke?: boolean;
  /** activity.read: Link auf Organisation › Verlauf */
  canOpenActivity?: boolean;
}) {
  const t = useTranslations("tenantSettings.publicLinks");
  const locale = useLocale();
  const showToast = useToast();
  const [links, setLinks] = useState(initialLinks);
  const [group, setGroup] = useState<Group>("all");
  const [onlyNever, setOnlyNever] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [partner, setPartner] = useState<string | null>(null);

  const neverExpiring = links.filter((link) => link.expiry === "never").length;
  const neverFilter = onlyNever && neverExpiring > 0;
  const base = neverFilter ? links.filter((link) => link.expiry === "never") : links;

  const counts = useMemo(() => {
    const result: Record<string, number> = {};
    for (const link of base) result[linkGroup(link.kind)] = (result[linkGroup(link.kind)] ?? 0) + 1;
    return result;
  }, [base]);
  const hasOther = links.some((link) => linkGroup(link.kind) === "other");
  const groups: Group[] = ["all", "files", "submissions", "calendar", "accounts", "partners", ...(hasOther ? (["other"] as Group[]) : [])];
  const visible = group === "all" ? base : base.filter((link) => linkGroup(link.kind) === group);

  const partners = useMemo(() => {
    const names = new Set<string>();
    for (const entry of history) names.add(entry.partner);
    for (const link of links) {
      const name = partnerOf(link);
      if (name) names.add(name);
    }
    return [...names].sort((a, b) => a.localeCompare(b, locale));
  }, [history, links, locale]);
  const historyVisible = partner ? history.filter((entry) => entry.partner === partner) : history;

  function selectGroup(next: string) {
    setGroup(next as Group);
    setConfirming(null);
    if (next !== "partners") setPartner(null);
  }

  function openHistory(name: string) {
    setGroup("partners");
    setPartner(name);
    setConfirming(null);
  }

  async function revoke(link: PublicLinkItem) {
    setBusy(link.id);
    try {
      await browserApiFetch(`/api/share-links/${link.id}`, { method: "DELETE" });
      setLinks((current) => current.filter((item) => !(item.kind === link.kind && item.id === link.id)));
      setConfirming(null);
      showToast(t("revoked", { name: link.label || "—" }), "success");
    } catch (error) {
      showToast(error instanceof Error && error.message ? error.message : t("revokeFailed"), "error");
    } finally {
      setBusy(null);
    }
  }

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

  // Erstellt/von steht nicht mehr sichtbar in der Zeile, sondern als Tooltip am Namen.
  function createdTitle(link: PublicLinkItem) {
    if (!link.created_at) return link.created_by ? t("createdBy", { name: link.created_by }) : undefined;
    const date = formatDate(link.created_at);
    return link.created_by ? t("createdAtBy", { date, name: link.created_by }) : t("createdAt", { date });
  }

  // Hinweis statt «Verwalten», wo hocX den Link nicht verwaltet
  function manageHint(link: PublicLinkItem) {
    if (link.manage_href) return null;
    if (link.kind.startsWith("calendar_")) return t("hint.calendar");
    if (link.kind === "share_album_partner") return t("hint.partner");
    return null;
  }

  function row(link: PublicLinkItem) {
    const key = `${link.kind}:${link.id}`;
    const linkGroupName = linkGroup(link.kind);
    const reasonText = reason(link);
    const partnerName = partnerOf(link);
    const hint = manageHint(link);
    const revocable = canRevoke && REVOCABLE.has(link.kind);
    const label = link.label || "—";
    return (
      <li key={key} className="public-links-row">
        <div className="public-links-row-main">
          <div className="public-links-row-name" title={createdTitle(link)}>{label}</div>
          <div className="public-links-row-meta">
            <span className={`public-links-kind public-links-kind-${linkGroupName}`}>{kindLabel(link.kind)}</span>
            <span aria-hidden="true"> · </span>
            <span className="public-links-row-reason" title={reasonText}>{reasonText}</span>
          </div>
        </div>
        <div className="public-links-row-validity">
          <span className={link.expiry === "never" ? "public-links-dot public-links-dot-warning" : "public-links-dot"} aria-hidden="true" />
          <span>{expiry(link)}</span>
          {link.last_used_at ? <span className="muted">{" · "}{t("lastUsed", { date: dayMonth(link.last_used_at) })}</span> : null}
        </div>
        <div className="public-links-row-actions">
          {hint ? <span className="muted public-links-row-hint">{hint}</span> : null}
          {partnerName && group !== "partners" ? (
            <button type="button" className="row-text-action public-links-action" onClick={() => openHistory(partnerName)}>
              {t("showHistory")}
            </button>
          ) : null}
          {revocable ? (
            <button
              type="button"
              className="row-text-action public-links-action public-links-action-revoke"
              aria-expanded={confirming === key}
              onClick={() => setConfirming(confirming === key ? null : key)}
            >
              {t("revoke")}
            </button>
          ) : null}
          {link.manage_href ? (
            <Link className="row-text-action public-links-action public-links-action-manage" href={link.manage_href as Route}>
              {t("manage")}
            </Link>
          ) : null}
        </div>
        {confirming === key ? (
          <div className="public-links-row-confirm" role="group" aria-label={t("revoke")}>
            <span className="public-links-row-confirm-text">{t("revokeInline", { name: label })}</span>
            <div className="public-links-row-confirm-actions">
              <button type="button" className="button-ghost" onClick={() => setConfirming(null)}>{t("cancel")}</button>
              <button type="button" className="button-danger" disabled={busy === link.id} onClick={() => void revoke(link)}>
                {t("revoke")}
              </button>
            </div>
          </div>
        ) : null}
      </li>
    );
  }

  function historyWhat(entry: PartnerHistoryEntry) {
    if (entry.event === "invited") return t("history.event.invited", { partner: entry.partner });
    if (entry.event === "accepted") return t("history.event.accepted");
    if (entry.event === "declined") return t("history.event.declined");
    return entry.expires_at
      ? t("history.event.publicLinkCreatedUntil", { name: entry.link_name ?? "—", date: formatDate(entry.expires_at) })
      : t("history.event.publicLinkCreated", { name: entry.link_name ?? "—" });
  }

  function historyActor(entry: PartnerHistoryEntry) {
    if (entry.actor === "partner") return entry.partner;
    return entry.person ? t("history.ownPerson", { name: entry.person }) : t("history.ownOrganisation");
  }

  const partnerHistory = (
    <section className="public-links-history" aria-labelledby="public-links-history-title">
      <div className="public-links-history-head">
        <div>
          <h2 id="public-links-history-title" className="public-links-history-title">{t("history.title")}</h2>
          <p className="muted public-links-history-lead">{t("history.description")}</p>
        </div>
        {partners.length > 0 ? (
          <div className="public-links-history-chips" role="group" aria-label={t("history.filterLabel")}>
            <button type="button" aria-pressed={partner === null} className={partner === null ? "button-pill button-pill-active" : "button-pill"} onClick={() => setPartner(null)}>
              {t("history.allPartners")}
            </button>
            {partners.map((name) => (
              <button key={name} type="button" aria-pressed={partner === name} className={partner === name ? "button-pill button-pill-active" : "button-pill"} onClick={() => setPartner(name)}>
                {name}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      {historyVisible.length === 0 ? (
        <p className="muted">{t("history.empty")}</p>
      ) : (
        <ul className="public-links-history-list">
          {historyVisible.map((entry, index) => (
            <li key={`${entry.at}:${entry.event}:${entry.partner}:${index}`} className="public-links-history-row">
              <time className="public-links-history-time" dateTime={entry.at}>{formatDateTime(entry.at, locale)}</time>
              <span className="public-links-history-actor">
                <span className={entry.actor === "partner" ? "public-links-dot public-links-dot-partner" : "public-links-dot public-links-dot-own"} aria-hidden="true" />
                {historyActor(entry)}
              </span>
              <span className="public-links-history-what">{historyWhat(entry)}</span>
              <Badge variant="neutral" className="public-links-history-album">{entry.album}</Badge>
            </li>
          ))}
        </ul>
      )}
      <p className="muted public-links-history-foot">
        {t.rich("history.footer", {
          link: (chunks) => (canOpenActivity ? <Link href={"/tenant-settings/activity" as Route}>{chunks}</Link> : <>{chunks}</>),
        })}
      </p>
    </section>
  );

  const body = (
    <div className="section-stack">
      {visible.length === 0 ? (
        <p className="muted public-links-empty">{links.length === 0 ? t("empty") : t("emptyFilter")}</p>
      ) : (
        <ul className="public-links-list">{visible.map(row)}</ul>
      )}
      {group === "partners" ? partnerHistory : null}
    </div>
  );

  return (
    <div className="section-stack public-links-overview">
      {mobile ? <p className="muted">{t("intro")}</p> : null}
      {neverExpiring > 0 ? (
        <div className="public-links-hint" role="status">
          <span className="public-links-dot public-links-dot-warning" aria-hidden="true" />
          <span className="public-links-hint-text">
            <strong>{t("neverExpiring.title", { count: neverExpiring })}</strong>{" "}
            <span className="muted">{t("neverExpiring.body", { count: neverExpiring })}</span>
          </span>
          <button type="button" className="button-secondary public-links-hint-toggle" aria-pressed={neverFilter} onClick={() => setOnlyNever(!neverFilter)}>
            {neverFilter ? t("neverExpiring.showAll") : t("neverExpiring.showOnly")}
          </button>
        </div>
      ) : null}
      <Tabs
        activeId={group}
        onChange={selectGroup}
        tabs={groups.map((value) => ({
          id: value,
          label: t(`group.${value}`),
          count: value === "all" ? base.length : counts[value] ?? 0,
          content: body,
        }))}
      />
    </div>
  );
}
