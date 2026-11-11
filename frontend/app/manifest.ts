import type { MetadataRoute } from "next";
import { getTranslations } from "next-intl/server";

// Web-App-Manifest (/manifest.webmanifest): hocX lässt sich ohne App Store als App installieren
// (iOS: Safari → Teilen → «Zum Home-Bildschirm», Android/Desktop: «App installieren»). Relative
// Pfade, damit dasselbe Manifest auf jeder Domain gilt (Haupt-, Mandanten- und Admin-Domain).
// Bewusst ohne Service Worker: keine Zwischenspeicherung von Protokolldaten auf dem Gerät, und
// nach einem Deploy läuft sofort der neue Stand.
// Farben = --bg aus design/tokens.css (Light); das Manifest kann keine CSS-Variablen lesen.
export const dynamic = "force-dynamic";

export default async function manifest(): Promise<MetadataRoute.Manifest> {
  const t = await getTranslations("common.meta");
  return {
    name: "hocX",
    short_name: "hocX",
    description: t("description"),
    id: "/",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#f6f7f9", // design-ok: Manifest kennt keine CSS-Variablen (= --bg Light)
    theme_color: "#f6f7f9", // design-ok: Manifest kennt keine CSS-Variablen (= --bg Light)
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
