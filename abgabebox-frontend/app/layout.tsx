import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Script from "next/script";
import "./tokens.css";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: "Abgabebox",
  description: "Dateien ohne Anmeldung einreichen",
  icons: { icon: "/favicon.ico" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="de" className={inter.variable} suppressHydrationWarning>
      <body suppressHydrationWarning>
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
          </header>
          <main>{children}</main>
          <footer className="page-footer">
            Copyright © 2026 hocX Project · All rights reserved.
          </footer>
        </div>
      </body>
    </html>
  );
}
