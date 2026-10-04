import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Script from "next/script";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages, getTranslations } from "next-intl/server";
import { LanguageSelect } from "@/components/language-select";
import "./tokens.css";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

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
    <html lang={locale} className={inter.variable} suppressHydrationWarning>
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
        <div className="page-shell">
          <header className="page-header">
            <img src="/favicon.ico" alt="hocX" />
            <span className="page-header-name">hocX</span>
            <LanguageSelect currentLocale={locale} />
          </header>
          <main>{children}</main>
          <footer className="page-footer">
            {t("copyright", { year: new Date().getFullYear() })}
          </footer>
        </div>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
