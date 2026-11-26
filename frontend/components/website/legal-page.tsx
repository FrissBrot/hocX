import type { ReactNode } from "react";
import { getLocale, getTranslations } from "next-intl/server";

import { WebsiteFooter, WEBSITE_CONTACT_FALLBACK } from "@/components/website/website-footer";
import { WebsiteLanguageSwitcher } from "@/components/website/website-language-switcher";
import { defaultLocale } from "@/i18n/locale-config.generated";
import { websiteBasePath, websiteHref } from "@/lib/website/paths";
import { formatLongDateRange } from "@/lib/utils/format";
import { getMainAppUrl } from "@/lib/site-config";

// Rechtstexte der oeffentlichen Website (Datenschutzerklaerung, Nutzungsbedingungen).
// Der Text steht vollstaendig in messages/<locale>/legal.json unter <kind>.sections: jeder Schluessel
// dort ist ein Abschnitt und zugleich sein Anker (#<schluessel>, in allen Sprachen gleich, damit
// verlinkte Anker nicht von der Sprache abhaengen). Innerhalb eines Abschnitts bestimmt das Praefix
// des Schluessels die Darstellung: title = Ueberschrift, p* = Absatz, h* = Zwischentitel,
// list* = Aufzaehlung (Objekt mit den Punkten). Massgebend ist die deutsche Fassung.

export type LegalKind = "privacy" | "terms";

// Stand der Texte (ISO). Bei jeder inhaltlichen Aenderung anpassen.
export const LEGAL_UPDATED: Record<LegalKind, string> = {
  privacy: "2026-11-26",
  terms: "2026-11-26",
};

// Kontakt des Betreibers (hocX project), auch fuer Datenschutzanfragen.
export const LEGAL_CONTACT_EMAIL = WEBSITE_CONTACT_FALLBACK;

type SectionContent = Record<string, string | Record<string, string>>;
export type LegalSections = Record<string, SectionContent>;

// E-Mail-Adresse und https-Adressen als Link, Platzhalter [[BITTE ERGAENZEN: ...]] hervorgehoben.
// Die Texte stammen ausschliesslich aus den eigenen Katalogen (keine Benutzerdaten).
const INLINE_PATTERN = /(\[\[[^\]]+\]\]|info@hocx\.ch|https:\/\/[^\s»"]+[^\s»".,;:)])/g;

function renderInline(text: string): ReactNode[] {
  return text.split(INLINE_PATTERN).map((part, index) => {
    if (part === LEGAL_CONTACT_EMAIL) {
      return (
        <a key={index} href={`mailto:${LEGAL_CONTACT_EMAIL}`}>
          {part}
        </a>
      );
    }
    if (part.startsWith("https://")) {
      return (
        <a key={index} href={part} rel="noopener noreferrer">
          {part}
        </a>
      );
    }
    if (part.startsWith("[[") && part.endsWith("]]")) {
      return (
        <mark key={index} className="ws-legal-placeholder">
          {part}
        </mark>
      );
    }
    return part;
  });
}

function renderBlock(key: string, value: string | Record<string, string>): ReactNode {
  if (typeof value !== "string") {
    return (
      <ul key={key} className="ws-legal-list">
        {Object.entries(value).map(([itemKey, item]) => (
          <li key={itemKey}>{renderInline(item)}</li>
        ))}
      </ul>
    );
  }
  if (key.startsWith("h")) {
    return (
      <h3 key={key} className="ws-legal-h3">
        {renderInline(value)}
      </h3>
    );
  }
  return <p key={key}>{renderInline(value)}</p>;
}

export async function LegalPage({ kind }: Readonly<{ kind: LegalKind }>) {
  const t = await getTranslations("legal");
  const tw = await getTranslations("website");
  const tf = await getTranslations("website.footer");
  const locale = await getLocale();
  const base = await websiteBasePath();
  const sections = t.raw(`${kind}.sections`) as LegalSections;
  const other: LegalKind = kind === "privacy" ? "terms" : "privacy";
  const appUrl = getMainAppUrl() ?? "";
  const updated = formatLongDateRange(LEGAL_UPDATED[kind], null, locale);

  return (
    <div className="ws-page">
      <header className="ws-header">
        <div className="ws-container ws-header-inner">
          <a href={websiteHref(base, "home")} className="ws-brand">
            <span className="ws-logo" aria-hidden="true">
              h
            </span>
            <span className="ws-brand-name">hocX</span>
          </a>
          <nav className="ws-nav" aria-label={t("common.navLabel")}>
            <a href={websiteHref(base, "privacy")} aria-current={kind === "privacy" ? "page" : undefined}>
              {t("common.privacy")}
            </a>
            <a href={websiteHref(base, "terms")} aria-current={kind === "terms" ? "page" : undefined}>
              {t("common.terms")}
            </a>
          </nav>
          <div className="ws-header-actions">
            <WebsiteLanguageSwitcher />
            <a href={`${appUrl}/login`} className="ws-link-quiet">
              {tw("nav.login")}
            </a>
          </div>
        </div>
      </header>

      <main id="top" className="ws-container ws-legal">
        <div className="ws-legal-head">
          <div className="ws-eyebrow">{t("common.eyebrow")}</div>
          <h1 className="ws-h2">{t(`${kind}.title`)}</h1>
          <p className="ws-legal-lead">{t(`${kind}.lead`)}</p>
          <p className="ws-legal-meta">
            <span>{t("common.updated", { date: updated })}</span>
            <span>
              {t("common.contactLabel")} <a href={`mailto:${LEGAL_CONTACT_EMAIL}`}>{LEGAL_CONTACT_EMAIL}</a>
            </span>
          </p>
          {locale !== defaultLocale ? <p className="ws-legal-authoritative">{t("common.authoritative")}</p> : null}
        </div>

        <div className="ws-legal-layout">
          <nav className="ws-legal-toc" aria-labelledby="legal-toc-title">
            <h2 id="legal-toc-title" className="ws-eyebrow-small">
              {t("common.toc")}
            </h2>
            <ol>
              {Object.entries(sections).map(([id, section]) => (
                <li key={id}>
                  <a href={`#${id}`}>{section.title as string}</a>
                </li>
              ))}
            </ol>
          </nav>

          <article className="ws-legal-body">
            {Object.entries(sections).map(([id, section]) => (
              <section key={id} id={id} className="ws-legal-section" aria-labelledby={`${id}-title`}>
                <h2 id={`${id}-title`} className="ws-legal-h2">
                  {section.title as string}
                </h2>
                {Object.entries(section)
                  .filter(([key]) => key !== "title")
                  .map(([key, value]) => renderBlock(key, value))}
              </section>
            ))}
            <p className="ws-legal-see-also">
              {t("common.seeAlso")} <a href={websiteHref(base, other)}>{t(`common.${other}`)}</a>
              {" · "}
              <a href="#top">{t("common.backToTop")}</a>
            </p>
          </article>
        </div>
      </main>

      <WebsiteFooter t={tf} base={base} appLoginUrl={`${appUrl}/login`} />
    </div>
  );
}
