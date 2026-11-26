import { websiteHref } from "@/lib/website/paths";

// Fusszeile aller Website-Seiten (Startseite und Rechtstexte). Bewusst synchron: die Seite
// uebergibt die Uebersetzungsfunktion des Namespaces website.footer (CLAUDE.md, i18n Regel 3).
export const WEBSITE_CONTACT_FALLBACK = "info@hocx.ch"; // i18n-ok: E-Mail-Adresse des Betreibers, kein UI-Text

type FooterT = (key: "copyright" | "privacy" | "terms" | "contact" | "login" | "navLabel", values?: { year: number }) => string;

export function WebsiteFooter({
  t,
  base,
  appLoginUrl,
  contactHref,
}: Readonly<{ t: FooterT; base: string; appLoginUrl: string; contactHref?: string | null }>) {
  return (
    <footer className="ws-footer">
      <div className="ws-container ws-footer-inner">
        <div className="ws-brand">
          <span className="ws-logo ws-logo-small" aria-hidden="true">
            h
          </span>
          <span className="ws-footer-copy">{t("copyright", { year: new Date().getFullYear() })}</span>
        </div>
        <nav className="ws-footer-links" aria-label={t("navLabel")}>
          <a href={websiteHref(base, "privacy")}>{t("privacy")}</a>
          <a href={websiteHref(base, "terms")}>{t("terms")}</a>
          <a href={contactHref ?? `mailto:${WEBSITE_CONTACT_FALLBACK}`}>{t("contact")}</a>
          <a href={appLoginUrl}>{t("login")}</a>
        </nav>
      </div>
    </footer>
  );
}
