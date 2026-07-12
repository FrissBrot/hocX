import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Abgabebox",
  description: "Dateien ohne Anmeldung einreichen",
  icons: { icon: "/favicon.ico" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="de">
      <body>
        <div className="page-shell">
          <header className="page-header">
            <img src="/favicon.ico" alt="hocX" />
            <span className="page-header-name">hocX</span>
          </header>
          <main>{children}</main>
        </div>
      </body>
    </html>
  );
}
