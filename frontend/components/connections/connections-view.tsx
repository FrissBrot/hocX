"use client";

import { ReactNode, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MobileIcon } from "@/components/mobile/mobile-icons";
import { useOpenMore } from "@/components/mobile/mobile-shell";
import { MobileSubHeader } from "@/components/mobile/mobile-ui";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { CopyField } from "@/components/ui/copy-field";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { appleSubscribeUrl, calendarFeedUrl, canSubscribeCalendar, googleSubscribeUrl } from "@/lib/calendar-feeds";
import { formatDateTime } from "@/lib/utils/format";
import type { CalendarFeed, CalendarFeedKind } from "@/types/api";

type Options = Pick<CalendarFeed, "todo_scope" | "include_completed" | "hide_details">;

const DEFAULT_OPTIONS: Options = { todo_scope: "mine", include_completed: false, hide_details: false };

const STATUS_VARIANT: Record<CalendarFeed["status"] | "off", BadgeVariant> = { active: "success", invalid: "danger", off: "neutral" };

/** Seite "Verknuepfungen" (Benutzermenue): Termine und Todos als abonnierbare Kalender fuer
 * Apple Kalender / Google Kalender. Desktop und Mobile teilen Logik und Karten, nur Kopf und
 * Abstaende unterscheiden sich (`mobile`). */
export function ConnectionsView({
  initialFeeds,
  role,
  tenantName,
  mobile = false,
}: {
  initialFeeds: CalendarFeed[];
  role: string | null;
  tenantName: string;
  mobile?: boolean;
}) {
  const t = useTranslations("connections");
  const [feeds, setFeeds] = useState<CalendarFeed[]>(initialFeeds);
  // Erst nach dem Mount bekannt - die Abo-Links brauchen die echte Origin (sonst Hydration-Abweichung).
  const [origin, setOrigin] = useState<string | null>(null);

  useEffect(() => {
    setOrigin(window.location.origin);
  }, []);

  const kinds = (["events", "todos"] as CalendarFeedKind[]).filter((kind) => canSubscribeCalendar(role, kind));

  function replaceFeed(kind: CalendarFeedKind, next: CalendarFeed | null) {
    setFeeds((current) => [...current.filter((feed) => feed.kind !== kind), ...(next ? [next] : [])]);
  }

  const cards = (
    <>
      {kinds.map((kind) => (
        <FeedCard
          key={kind}
          kind={kind}
          feed={feeds.find((feed) => feed.kind === kind) ?? null}
          tenantName={tenantName}
          origin={origin}
          mobile={mobile}
          onChange={(next) => replaceFeed(kind, next)}
        />
      ))}
      <HowTo mobile={mobile} />
    </>
  );

  if (mobile) {
    return <MobileConnections>{cards}</MobileConnections>;
  }

  return (
    <div className="grid connections-page">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("page.title")}</h1>
          <p className="muted">{t("page.description")}</p>
        </div>
      </div>
      <div className="connections-cards">{cards}</div>
    </div>
  );
}

function MobileConnections({ children }: { children: ReactNode }) {
  const t = useTranslations("connections");
  const tMobile = useTranslations("mobile");
  const openMore = useOpenMore();
  return (
    <div className="mobile-page mobile-page-list connections-mobile">
      <MobileSubHeader title={t("page.title")} subtitle={t("page.description")} backLabel={tMobile("tabs.more")} onBack={openMore} />
      <div className="mobile-section grid connections-cards">{children}</div>
    </div>
  );
}

function FeedCard({
  kind,
  feed,
  tenantName,
  origin,
  mobile,
  onChange,
}: {
  kind: CalendarFeedKind;
  feed: CalendarFeed | null;
  tenantName: string;
  origin: string | null;
  mobile: boolean;
  onChange: (next: CalendarFeed | null) => void;
}) {
  const t = useTranslations("connections");
  const locale = useLocale();
  const showToast = useToast();
  const confirm = useConfirm();
  const [busy, setBusy] = useState(false);
  // Vor dem Anlegen gewaehlte Optionen; danach gilt der gespeicherte Stand (jede Aenderung speichert sofort).
  const [draft, setDraft] = useState<Options>(DEFAULT_OPTIONS);
  const options: Options = feed ?? draft;
  const status = feed?.status ?? "off";

  async function save(next: Options, successToast: string) {
    setBusy(true);
    try {
      const saved = await browserApiFetch<CalendarFeed>(`/api/calendar-feeds/${kind}`, {
        method: "PUT",
        body: JSON.stringify({ calendar_name: t(`${kind}.calendarName`, { tenant: tenantName }), ...next }),
      });
      onChange(saved);
      showToast(successToast, "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.failed"), "error");
    } finally {
      setBusy(false);
    }
  }

  function updateOption(patch: Partial<Options>) {
    const next = { ...options, ...patch };
    if (feed) {
      void save(next, t("toasts.saved"));
    } else {
      setDraft(next);
    }
  }

  async function regenerate() {
    if (!(await confirm({ message: t("confirm.regenerate"), tone: "danger", confirmLabel: t("confirm.regenerateLabel") }))) return;
    setBusy(true);
    try {
      onChange(await browserApiFetch<CalendarFeed>(`/api/calendar-feeds/${kind}/regenerate`, { method: "POST" }));
      showToast(t("toasts.regenerated"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.failed"), "error");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!(await confirm({ message: t("confirm.remove"), tone: "danger", confirmLabel: t("confirm.removeLabel") }))) return;
    setBusy(true);
    try {
      await browserApiFetch(`/api/calendar-feeds/${kind}`, { method: "DELETE" });
      onChange(null);
      setDraft(DEFAULT_OPTIONS);
      showToast(t("toasts.removed"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.failed"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={`${mobile ? "mobile-card" : "section-card"} connections-card`} aria-labelledby={`connections-${kind}-title`}>
      <div className="connections-card-header">
        <span className="connections-card-icon" aria-hidden="true">
          <MobileIcon name={kind === "events" ? "calendar" : "todos"} size={20} />
        </span>
        <div className="connections-card-heading">
          <div className="connections-card-title-row">
            <h2 id={`connections-${kind}-title`} className="connections-card-title">
              {t(`${kind}.title`)}
            </h2>
            <Badge variant={STATUS_VARIANT[status]} dot>
              {t(`status.${status}`)}
            </Badge>
          </div>
          <p className="connections-card-description">{t(`${kind}.description`, { tenant: tenantName })}</p>
        </div>
      </div>

      {feed?.status === "invalid" ? <StatusBanner tone="error" message={t("invalid")} /> : null}

      {feed?.status === "active" && origin ? (
        <>
          <div className="connections-subscribe">
            <a className="connections-subscribe-link" href={appleSubscribeUrl(feed.path, origin)}>
              <CalendarGlyph />
              {t("actions.apple")}
            </a>
            <a className="connections-subscribe-link" href={googleSubscribeUrl(feed.path, origin)} target="_blank" rel="noopener noreferrer">
              <ExternalGlyph />
              {t("actions.google")}
            </a>
          </div>
          <div className="field-stack connections-url">
            <span className="field-label">{t("url.label")}</span>
            <CopyField label={t("url.label")} value={calendarFeedUrl(feed.path, origin)} />
            <span className="field-help">{t("url.help")}</span>
          </div>
        </>
      ) : null}

      <fieldset className="share-metadata-fieldset connections-options" disabled={busy}>
        {kind === "todos" ? (
          <label className="field-stack">
            <span className="field-label">{t("options.scope")}</span>
            <select value={options.todo_scope} onChange={(event) => updateOption({ todo_scope: event.target.value as Options["todo_scope"] })}>
              <option value="mine">{t("options.scopeMine")}</option>
              <option value="all">{t("options.scopeAll")}</option>
            </select>
          </label>
        ) : null}
        {kind === "todos" ? (
          <Switch checked={options.include_completed} onChange={(value) => updateOption({ include_completed: value })} label={t("options.includeCompleted")} />
        ) : null}
        <Switch
          checked={options.hide_details}
          onChange={(value) => updateOption({ hide_details: value })}
          label={t("options.hideDetails")}
          help={t("options.hideDetailsHelp")}
        />
      </fieldset>

      <div className="connections-card-footer">
        {feed ? (
          <>
            <span className="connections-card-meta">
              {feed.last_accessed_at ? t("meta.lastAccess", { date: formatDateTime(feed.last_accessed_at, locale) }) : t("meta.neverAccessed")}
            </span>
            <div className="connections-card-actions">
              <button type="button" className="button-ghost" disabled={busy} onClick={() => void regenerate()}>
                {t("actions.regenerate")}
              </button>
              <button type="button" className="button-danger" disabled={busy} onClick={() => void remove()}>
                {t("actions.remove")}
              </button>
            </div>
          </>
        ) : (
          <button type="button" className="button-primary connections-enable" disabled={busy} onClick={() => void save(options, t("toasts.enabled"))}>
            {t("actions.enable")}
          </button>
        )}
      </div>
    </section>
  );
}

function Switch({ checked, onChange, label, help }: { checked: boolean; onChange: (value: boolean) => void; label: string; help?: string }) {
  return (
    <label className="share-metadata-option">
      <input type="checkbox" role="switch" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span className="album-picker-switch-track" aria-hidden="true" />
      <span className="share-metadata-text">
        <span>{label}</span>
        {help ? <span className="field-help">{help}</span> : null}
      </span>
    </label>
  );
}

function HowTo({ mobile }: { mobile: boolean }) {
  const t = useTranslations("connections");
  return (
    <section className={`${mobile ? "mobile-card" : "section-card"} connections-card connections-howto`} aria-labelledby="connections-howto-title">
      <h2 id="connections-howto-title" className="connections-card-title">
        {t("howto.title")}
      </h2>
      <ul className="connections-howto-list">
        <li>{t("howto.apple")}</li>
        <li>{t("howto.google")}</li>
        <li>{t("howto.android")}</li>
        <li>{t("howto.readOnly")}</li>
      </ul>
    </section>
  );
}

// Neutrale Symbole statt Markenlogos (Kalender bzw. "oeffnet extern") - Farbe aus currentColor.
function CalendarGlyph() {
  return (
    <svg viewBox="0 0 24 24" width={18} height={18} fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3.5" y="5" width="17" height="15.5" rx="2" />
      <path d="M3.5 10h17M8 3v4M16 3v4" />
    </svg>
  );
}

function ExternalGlyph() {
  return (
    <svg viewBox="0 0 24 24" width={18} height={18} fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14 4h6v6M20 4l-8 8" />
      <path d="M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10" />
    </svg>
  );
}
