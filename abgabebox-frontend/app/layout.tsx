import type { Metadata } from "next";
import { Inter, Source_Serif_4 } from "next/font/google";
import Script from "next/script";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages, getTranslations } from "next-intl/server";
import { FlowProvider, FlowStepBar, FlowStepList } from "@/components/flow-steps";
import { BrandIntro, BrandNote, BrandSubtitle } from "@/components/brand-intro";
import { LanguageSelect } from "@/components/language-select";
import { MaintenanceBanner } from "@/components/maintenance-banner";
import "./tokens.css";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
// Serifenschrift nur fuer Ueberschriften (Abgabebox-Redesign), Fliesstext bleibt Inter wie in der Haupt-App.
const serif = Source_Serif_4({ subsets: ["latin"], weight: ["600"], variable: "--font-serif", display: "swap" });

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("abgabebox.meta");
  return {
    title: "Abgabebox",
    description: t("description"),
    icons: { icon: "/favicon.ico" },
  };
}

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const locale = await getLocale();
  const messages = await getMessages();
  const t = await getTranslations("abgabebox");

  return (
    <html lang={locale} className={`${inter.variable} ${serif.variable}`} suppressHydrationWarning>
      <body suppressHydrationWarning>
        <NextIntlClientProvider locale={locale} messages={messages}>
        {/* Gleiche Theme-Logik wie die Haupt-App (frontend/app/layout.tsx): gespeicherte
            Praeferenz, sonst System. Ohne JS greift der prefers-color-scheme-Block in tokens.css. */}
        <Script
          id="hocx-theme"
          strategy="beforeInteractive"
          dangerouslySetInnerHTML={{
            __html: `
              (function () {
                try {
                  var stored = null;
                  try { stored = localStorage.getItem("hocx-theme"); } catch (error) {}
                  var preference = stored || "auto";
                  var theme = preference === "auto"
                    ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
                    : preference;
                  document.documentElement.dataset.theme = theme;
                } catch (error) {}
              })();
            `
          }}
        />
        <FlowProvider>
          <div className="box-shell">
            <aside className="box-brand">
              <div className="box-brand-top">
                <span className="box-brand-logo">
                  <img src="/favicon.ico" alt="" />
                </span>
                <span className="box-brand-name">
                  <span className="box-brand-title">hocX</span>
                  <span className="box-brand-sub"><BrandSubtitle /></span>
                </span>
                <LanguageSelect currentLocale={locale} />
              </div>
              <FlowStepBar />
              <BrandIntro />
              <FlowStepList />
              <div className="box-brand-note">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                  <rect x="5" y="11" width="14" height="9" rx="2" />
                  <path d="M8 11V8a4 4 0 0 1 8 0v3" />
                </svg>
                <BrandNote />
              </div>
            </aside>
            <div className="box-main">
              <main className="box-content">
                <MaintenanceBanner />
                {children}
              </main>
              <footer className="page-footer">
                {t("copyright", { year: new Date().getFullYear() })}
              </footer>
            </div>
          </div>
        </FlowProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
