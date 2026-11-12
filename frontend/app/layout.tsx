import type { Metadata, Viewport } from "next";
import { getServerVersion } from "@/lib/server-version";
import { headers } from "next/headers";
import { Inter } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages, getTranslations } from "next-intl/server";
import { getMainAppUrl } from "@/lib/site-config";
import { ClientMessagesBridge } from "@/components/i18n/client-messages-bridge";
import { ViewportProvider } from "@/lib/hooks/use-is-mobile";
import { isMobileUserAgent } from "@/lib/utils/viewport";
import { NONCE_HEADER } from "@/lib/csp";
import { pickNamespaces, ROOT_NAMESPACES } from "@/lib/i18n/message-scopes";
import "./tokens.css";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export async function generateMetadata(): Promise<Metadata> {
  const baseUrl = getMainAppUrl();
  const metadataBase = baseUrl ? new URL(baseUrl) : undefined;
  const t = await getTranslations("common.meta");

  return {
    metadataBase,
    title: "hocX",
    description: t("description"),
    // Installierbar als App (app/manifest.ts); iOS liest Icon und Vollbild aus diesen Angaben
    manifest: "/manifest.webmanifest",
    icons: { apple: "/icons/apple-touch-icon.png" },
    appleWebApp: { capable: true, title: "hocX", statusBarStyle: "default" },
  };
}

// viewport-fit=cover: die Mobile-Tableiste reserviert ueber env(safe-area-inset-bottom) selbst
// Platz fuer den Home-Indikator, statt dass der Browser einen leeren Streifen darunter laesst.
// themeColor färbt die Statusleiste der installierten App passend zum Theme (= --bg in tokens.css).
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f7f9" }, // design-ok: Meta-Tag kennt keine CSS-Variablen (= --bg Light)
    { media: "(prefers-color-scheme: dark)", color: "#0e1420" }, // design-ok: Meta-Tag kennt keine CSS-Variablen (= --bg Dark)
  ],
};

// Ohne das wuerde Next.js Routen ohne eigene dynamische Datenabhaengigkeit (z.B. /login)
// statisch zur Build-Zeit vorrendern - dann wuerde das untenstehende __HOCX_CONFIG__-Script
// mit den (in der CI unbekannten) Werten der Build-Umgebung eingefroren, statt bei jedem
// Request die echten Laufzeit-Werte (Domain/Version dieser konkreten Umgebung) zu lesen.
export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // Server-seitig gelesen (nicht NEXT_PUBLIC_*), damit dasselbe, in der CI gebaute Image
  // in Test und Prod mit unterschiedlichen Domains/Versionen laufen kann, ohne dass diese
  // Werte zur Build-Zeit im Client-Bundle eingefroren werden.
  const runtimeConfig = {
    mainAppDomain: process.env.TRAEFIK_DOMAIN || null,
    docsDomain: process.env.TRAEFIK_DOCS_DOMAIN || null,
    ...getServerVersion()
  };

  // Aufgeloest von i18n/request.ts (Cookie > Accept-Language > Default) - siehe dort fuer die
  // volle Prioritaetskette inkl. der gespeicherten Benutzerpraeferenz.
  const locale = await getLocale();
  // Nur die global gebrauchten Namespaces; die Bereiche legen ihre eigenen per AreaIntlProvider
  // in ihrem layout.tsx nach (siehe lib/i18n/message-scopes.ts).
  const messages = pickNamespaces(await getMessages(), ROOT_NAMESPACES);
  const requestHeaders = await headers();
  const initialMobile = isMobileUserAgent(requestHeaders.get("user-agent"));
  // Von proxy.ts pro Request gesetzt (Nonce-CSP, MAIN-FE-013).
  const nonce = requestHeaders.get(NONCE_HEADER) ?? undefined;

  return (
    <html lang={locale} className={inter.variable} suppressHydrationWarning>
      {/* Plain script statt next/script: Next 16/React 19 warnt bei Script strategy beforeInteractive
          im body ("Encountered a script tag while rendering React component"). Das Layout ist eine
          Server Component, die Tags landen also unveraendert im initialen HTML und laufen vor der Hydration. */}
      <head>
        <script
          id="hocx-runtime-config"
          nonce={nonce}
          dangerouslySetInnerHTML={{
            __html: `window.__HOCX_CONFIG__ = ${JSON.stringify(runtimeConfig).replace(/</g, "\\u003c")};`
          }}
        />
        <script
          id="hocx-theme"
          nonce={nonce}
          dangerouslySetInnerHTML={{
            __html: `
              (function () {
                try {
                  var stored = localStorage.getItem("hocx-theme");
                  var preference = stored || "auto";
                  var theme = preference === "auto"
                    ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
                    : preference;
                  document.documentElement.dataset.themePreference = preference;
                  document.documentElement.dataset.theme = theme;
                } catch (error) {}
              })();
            `
          }}
        />
      </head>
      <body suppressHydrationWarning>
        <NextIntlClientProvider locale={locale} messages={messages}>
          <ClientMessagesBridge />
          <ViewportProvider initialMobile={initialMobile}>{children}</ViewportProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
