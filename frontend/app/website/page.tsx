import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { WebsitePricing } from "@/components/website/website-pricing";
import { backendFetch } from "@/lib/api/client";
import { getMainAppUrl } from "@/lib/site-config";
import type { PublicCustomer, PublicPlan } from "@/types/api";

// Oeffentliche Landing Page (Hauptdomain, siehe TRAEFIK_WEBSITE_DOMAIN in proxy.ts). Texte kommen
// aus messages/<locale>/website.json, Preise und Abos bei jedem Request frisch aus dem
// Preiskatalog (GET /api/public/plans), die Kundenliste aus den im Adminportal freigegebenen
// Mandanten (GET /api/public/customers) - Aenderungen dort sind sofort sichtbar.

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("website.meta");
  return { title: t("title"), description: t("description") };
}

const AGENDA_KEYS = ["agendaWelcome", "agendaAttendance", "agendaFinances", "agendaAnniversary", "agendaTodos", "agendaMisc"] as const;
const ACTIVE_AGENDA = "agendaFinances";
const TRANSACTIONS = ["tx1", "tx2", "tx3"] as const;
const EVENTS = [
  { key: "event1", tag: "tagBoard", tone: "board", cancelled: false },
  { key: "event2", tag: "tagEvent", tone: "event", cancelled: false },
  { key: "event3", tag: "tagProject", tone: "project", cancelled: true },
] as const;
const AVATARS = [
  { initials: "AM", tone: "1" }, // i18n-ok: Initialen im Mockup
  { initials: "LK", tone: "2" }, // i18n-ok: Initialen im Mockup
  { initials: "RB", tone: "3" }, // i18n-ok: Initialen im Mockup
] as const;

export default async function WebsitePage() {
  const t = await getTranslations("website");
  const [plans, customers] = await Promise.all([
    backendFetch<PublicPlan[]>("/api/public/plans").then((result) => result ?? []),
    backendFetch<PublicCustomer[]>("/api/public/customers").then((result) => result ?? []),
  ]);
  const appUrl = getMainAppUrl() ?? "";
  const appLoginUrl = `${appUrl}/login`;
  const contactEmail = process.env.WEBSITE_CONTACT_EMAIL?.trim() || null;
  const contactHref = contactEmail ? `mailto:${contactEmail}` : null;
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>;

  return (
    <div className="ws-page">
      <header className="ws-header">
        <div className="ws-container ws-header-inner">
          <a href="#top" className="ws-brand">
            <span className="ws-logo" aria-hidden="true">
              h
            </span>
            <span className="ws-brand-name">hocX</span>
          </a>
          <nav className="ws-nav" aria-label={t("nav.label")}>
            <a href="#ablauf">{t("nav.howItWorks")}</a>
            <a href="#funktionen">{t("nav.features")}</a>
            <a href="#preise">{t("nav.pricing")}</a>
          </nav>
          <div className="ws-header-actions">
            <a href={appLoginUrl} className="ws-link-quiet">
              {t("nav.login")}
            </a>
            <a href="#preise" className="ws-button ws-button-small">
              {t("nav.tryFree")}
            </a>
          </div>
        </div>
      </header>

      <main>
        <section id="top" className="ws-container ws-hero">
          <div className="ws-hero-copy">
            <div className="ws-announce">
              <span className="ws-announce-tag">{t("hero.badgeNew")}</span>
              {t("hero.badgeText")}
            </div>
            <h1 className="ws-display">
              {t("hero.titleLead")} <em>{t("hero.titleEmphasis")}</em>
            </h1>
            <p className="ws-hero-lead">{t("hero.lead")}</p>
            <div className="ws-hero-actions">
              <a href="#preise" className="ws-button">
                {t("hero.ctaPrimary")}
              </a>
              <a href="#ablauf" className="ws-button ws-button-outline">
                {t("hero.ctaSecondary")}
              </a>
              <span className="ws-hero-note">{t("hero.note")}</span>
            </div>
          </div>

          <div className="ws-mock-wrap" aria-hidden="true">
            <div className="ws-mock">
              <div className="ws-mock-bar">
                <span className="ws-mock-dot" />
                <span className="ws-mock-dot" />
                <span className="ws-mock-dot" />
                <span className="ws-mock-url">{t("mock.url")}</span>
              </div>
              <div className="ws-mock-body">
                <div className="ws-mock-agenda">
                  <div className="ws-eyebrow-small">{t("mock.agendaLabel")}</div>
                  {AGENDA_KEYS.map((key, index) => (
                    <div key={key} className={key === ACTIVE_AGENDA ? "ws-mock-agenda-item ws-mock-agenda-item-active" : "ws-mock-agenda-item"}>
                      {t("mock.agendaItem", { number: index + 1, title: t(`mock.${key}`) })}
                    </div>
                  ))}
                </div>
                <div className="ws-mock-main">
                  <div>
                    <div className="ws-mock-meta">{t("mock.meetingMeta")}</div>
                    <div className="ws-mock-title">{t("mock.agendaItem", { number: 3, title: t("mock.agendaFinances") })}</div>
                  </div>
                  <div className="ws-mock-stats">
                    <div className="ws-mock-stat">
                      <div className="ws-mock-stat-label">{t("mock.balanceLabel")}</div>
                      <div className="ws-mock-stat-value">{t("mock.balanceValue")}</div>
                    </div>
                    <div className="ws-mock-stat">
                      <div className="ws-mock-stat-label">{t("mock.deltaLabel")}</div>
                      <div className="ws-mock-stat-value ws-positive">{t("mock.deltaValue")}</div>
                    </div>
                  </div>
                  <div className="ws-mock-table">
                    <div className="ws-mock-row ws-mock-row-head">
                      <span>{t("mock.colDate")}</span>
                      <span>{t("mock.colDescription")}</span>
                      <span className="ws-align-end">{t("mock.colAmount")}</span>
                    </div>
                    {TRANSACTIONS.map((key) => (
                      <div key={key} className="ws-mock-row">
                        <span className="ws-muted">{t(`mock.${key}Date`)}</span>
                        <span>{t(`mock.${key}Text`)}</span>
                        <span className="ws-align-end ws-strong">{t(`mock.${key}Amount`)}</span>
                      </div>
                    ))}
                  </div>
                  <p className="ws-mock-note">
                    {t.rich("mock.note", { strong })}
                    <span className="ws-mock-caret" />
                  </p>
                </div>
                <div className="ws-mock-side">
                  <div className="ws-mock-side-head">
                    <span className="ws-eyebrow-small">{t("mock.liveLabel")}</span>
                    <div className="ws-avatars">
                      {AVATARS.map((avatar) => (
                        <span key={avatar.initials} className={`ws-avatar ws-avatar-${avatar.tone}`}>
                          {avatar.initials}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="ws-eyebrow-small">{t("mock.newTodos")}</div>
                  <div className="ws-mock-todos">
                    {(["todo1", "todo2"] as const).map((key) => (
                      <div key={key} className="ws-mock-todo">
                        <div className="ws-mock-todo-title">{t(`mock.${key}Title`)}</div>
                        <div className="ws-mock-todo-meta">{t(`mock.${key}Meta`)}</div>
                      </div>
                    ))}
                  </div>
                  <div className="ws-mock-saved">
                    <span className="ws-mock-saved-dot" />
                    {t("mock.autosaved")}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {customers.length > 0 ? (
          <section className="ws-container ws-customers" aria-label={t("customers.label")}>
            <span className="ws-customers-label">{t("customers.label")}</span>
            {customers.map((customer, index) => (
              <span key={`${customer.name}-${index}`} className="ws-customer">
                {customer.name}
              </span>
            ))}
          </section>
        ) : null}

        <section id="ablauf" className="ws-container ws-section">
          <div className="ws-section-intro-split">
            <h2 className="ws-h2">{t("steps.title")}</h2>
            <p className="ws-section-lead">{t("steps.lead")}</p>
          </div>
          <div className="ws-steps">
            {(["step1", "step2", "step3"] as const).map((key) => (
              <div key={key} className={key === "step2" ? "ws-step ws-step-highlight" : "ws-step"}>
                <span className="ws-step-label">{t(`steps.${key}Label`)}</span>
                <h3 className="ws-step-title">{t(`steps.${key}Title`)}</h3>
                <p className="ws-step-text">{t(`steps.${key}Text`)}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="funktionen" className="ws-container ws-section">
          <div className="ws-section-intro">
            <div className="ws-eyebrow">{t("features.eyebrow")}</div>
            <h2 className="ws-h2">{t("features.title")}</h2>
          </div>

          <div className="ws-feature-grid">
            <div className="ws-feature ws-feature-wide">
              <div className="ws-feature-copy">
                <h3 className="ws-h3-large">{t("features.eventsTitle")}</h3>
                <p className="ws-feature-text-large">{t("features.eventsText")}</p>
                <div className="ws-chips">
                  <span className="ws-tag ws-tag-meeting">{t("features.tagMeeting")}</span>
                  <span className="ws-tag ws-tag-project">{t("features.tagProject")}</span>
                  <span className="ws-tag ws-tag-board">{t("features.tagBoard")}</span>
                  <span className="ws-tag ws-tag-event">{t("features.tagEvent")}</span>
                </div>
              </div>
              <div className="ws-events" aria-hidden="true">
                {EVENTS.map((event) => (
                  <div key={event.key} className={event.cancelled ? "ws-event ws-event-cancelled" : "ws-event"}>
                    <div className="ws-event-date">
                      <div className="ws-event-month">{t(`features.${event.key}Month`)}</div>
                      <div className="ws-event-day">{t(`features.${event.key}Day`)}</div>
                    </div>
                    <div className="ws-event-body">
                      <div className="ws-event-title">{t(`features.${event.key}Title`)}</div>
                      <div className="ws-event-meta">{t(`features.${event.key}Meta`)}</div>
                    </div>
                    <span className={`ws-tag ws-tag-${event.tone}`}>{t(`features.${event.tag}`)}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="ws-feature">
              <h3 className="ws-h3">{t("features.attendanceTitle")}</h3>
              <p className="ws-feature-text">{t("features.attendanceText")}</p>
              <div className="ws-feature-foot ws-chips">
                <span className="ws-status ws-status-success">{t("features.present", { count: 14 })}</span>
                <span className="ws-status ws-status-warning">{t("features.excused", { count: 2 })}</span>
                <span className="ws-status ws-status-danger">{t("features.absent", { count: 1 })}</span>
              </div>
            </div>

            <div className="ws-feature">
              <h3 className="ws-h3">{t("features.submissionTitle")}</h3>
              <p className="ws-feature-text">{t("features.submissionText")}</p>
              <div className="ws-feature-foot ws-dropzone">{t.rich("features.submissionUrl", { strong })}</div>
            </div>

            <div className="ws-feature">
              <h3 className="ws-h3">{t("features.mediaTitle")}</h3>
              <p className="ws-feature-text">{t("features.mediaText")}</p>
              <div className="ws-feature-foot ws-thumbs" aria-hidden="true">
                <div className="ws-thumb ws-thumb-1" />
                <div className="ws-thumb ws-thumb-2" />
                <div className="ws-thumb ws-thumb-3" />
                <div className="ws-thumb ws-thumb-4">{t("features.mediaMore", { count: 248 })}</div>
              </div>
            </div>

            <div className="ws-feature">
              <h3 className="ws-h3">{t("features.importTitle")}</h3>
              <p className="ws-feature-text">{t("features.importText")}</p>
              <div className="ws-feature-foot ws-imports">
                <div className="ws-import-row">
                  <span>{t("features.import1File")}</span>
                  <span className="ws-import-done">{t("features.import1Status")}</span>
                </div>
                <div className="ws-import-row">
                  <span>{t("features.import2File")}</span>
                  <span className="ws-import-review">{t("features.import2Status")}</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="ws-container ws-section">
          <div className="ws-band">
            <div className="ws-band-copy">
              <div className="ws-eyebrow ws-band-eyebrow">{t("layouts.eyebrow")}</div>
              <h2 className="ws-h2 ws-h2-band">{t("layouts.title")}</h2>
              <p className="ws-band-text">{t("layouts.text")}</p>
            </div>
            <div className="ws-papers" aria-hidden="true">
              <div className="ws-paper ws-paper-cover">
                <div className="ws-paper-accent" />
                <div className="ws-paper-cover-title">
                  {t("layouts.coverTitle")}
                  <br />
                  {t("layouts.coverSubtitle")}
                </div>
                <div className="ws-paper-meta">{t("layouts.coverMeta")}</div>
                <div className="ws-paper-rule" />
                <div className="ws-paper-org">{t("layouts.organisation")}</div>
              </div>
              <div className="ws-paper ws-paper-page">
                <div className="ws-paper-header">
                  <span>{t("layouts.organisation")}</span>
                  <span>{t("layouts.pageNumber", { page: 3 })}</span>
                </div>
                <div className="ws-paper-heading">{t("mock.agendaItem", { number: 3, title: t("mock.agendaFinances") })}</div>
                <div className="ws-paper-line" />
                <div className="ws-paper-line ws-paper-line-85" />
                <div className="ws-paper-line ws-paper-line-92" />
                <div className="ws-paper-table" />
                <div className="ws-paper-heading">{t("mock.agendaItem", { number: 4, title: t("layouts.sectionAnniversary") })}</div>
                <div className="ws-paper-line" />
                <div className="ws-paper-line ws-paper-line-70" />
              </div>
            </div>
          </div>
        </section>

        <section id="preise" className="ws-container ws-section">
          <WebsitePricing
            plans={plans}
            contactEmail={contactEmail}
            appLoginUrl={appLoginUrl}
            heading={
              <div className="ws-pricing-intro">
                <div className="ws-eyebrow">{t("pricing.eyebrow")}</div>
                <h2 className="ws-h2">{t("pricing.title")}</h2>
                <p className="ws-pricing-note">{t("pricing.note")}</p>
              </div>
            }
          />
        </section>

        <section className="ws-container ws-section ws-final">
          <h2 className="ws-display ws-display-final">
            {t("cta.titleLead")} <em>{t("cta.titleEmphasis")}</em>
          </h2>
          <p className="ws-final-text">{t("cta.text")}</p>
          <div className="ws-final-actions">
            <a href="#preise" className="ws-button">
              {t("cta.start")}
            </a>
            {contactHref ? (
              <a href={contactHref} className="ws-button ws-button-outline">
                {t("cta.demo")}
              </a>
            ) : null}
          </div>
        </section>
      </main>

      <footer className="ws-footer">
        <div className="ws-container ws-footer-inner">
          <div className="ws-brand">
            <span className="ws-logo ws-logo-small" aria-hidden="true">
              h
            </span>
            <span className="ws-footer-copy">{t("footer.copyright", { year: new Date().getFullYear() })}</span>
          </div>
          <div className="ws-footer-links">
            {contactHref ? <a href={contactHref}>{t("footer.contact")}</a> : null}
            <a href={appLoginUrl}>{t("footer.login")}</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
