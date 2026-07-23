import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "hocX",
  description: "Protocol and template management workspace"
};

// Ohne das wuerde Next.js Routen ohne eigene dynamische Datenabhaengigkeit (z.B. /login)
// statisch zur Build-Zeit vorrendern - dann wuerde das untenstehende __HOCX_CONFIG__-Script
// mit den (in der CI unbekannten) Werten der Build-Umgebung eingefroren, statt bei jedem
// Request die echten Laufzeit-Werte (Domain/Version dieser konkreten Umgebung) zu lesen.
export const dynamic = "force-dynamic";

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // Server-seitig gelesen (nicht NEXT_PUBLIC_*), damit dasselbe, in der CI gebaute Image
  // in Test und Prod mit unterschiedlichen Domains/Versionen laufen kann, ohne dass diese
  // Werte zur Build-Zeit im Client-Bundle eingefroren werden.
  const runtimeConfig = {
    mainAppDomain: process.env.TRAEFIK_DOMAIN || null,
    version: process.env.HOCX_VERSION || "dev"
  };

  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <script
          dangerouslySetInnerHTML={{
            __html: `window.__HOCX_CONFIG__ = ${JSON.stringify(runtimeConfig).replace(/</g, "\\u003c")};`
          }}
        />
        <script
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
        {children}
      </body>
    </html>
  );
}
