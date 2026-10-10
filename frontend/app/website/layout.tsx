import type { CSSProperties } from "react";
import { Public_Sans, Source_Serif_4 } from "next/font/google";

// Eigene Schriften nur fuer die oeffentliche Website (Landing Page), die App selbst bleibt bei Inter.
const serif = Source_Serif_4({ subsets: ["latin"], style: ["normal", "italic"], axes: ["opsz"], display: "swap" });
const sans = Public_Sans({ subsets: ["latin"], display: "swap" });

export default function WebsiteLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const fontVars = {
    "--ws-font-serif": serif.style.fontFamily,
    "--ws-font-sans": sans.style.fontFamily,
  } as CSSProperties;
  return (
    <div className="website" style={fontVars}>
      {children}
    </div>
  );
}
