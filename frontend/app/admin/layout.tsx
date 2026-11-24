import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { AreaIntlProvider } from "@/components/i18n/area-intl-provider";
import "@/app/styles/admin.css";
import "@/app/styles/admin-analytics.css";
import "@/app/styles/admin-overview.css";
import "@/app/styles/admin-tenant-detail.css";
import "@/app/styles/admin-audit.css";
import "@/app/styles/uploads.css";

// Tab-Titel und eigenes Favicon der hocX Konsole (1.5.2): gleiches Zeichen wie die App, aber hell
// auf dunklem Grund, damit App und Konsole im Tab unterscheidbar sind. Gilt für alle /admin-Routen
// inkl. Login; ersetzt die Icons aus app/layout.tsx (App-Favicon und Manifest bleiben unverändert).
// /favicon.ico direkt auf der Admin-Domain liefert proxy.ts aus demselben Ordner.
export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("adminShell");
  return {
    title: t("title"),
    icons: {
      icon: [
        { url: "/icons/console/favicon.ico", sizes: "32x32" },
        { url: "/icons/console/icon.svg", type: "image/svg+xml" },
      ],
      apple: "/icons/console/apple-touch-icon.png",
    },
  };
}

// Liefert die Uebersetzungs-Namespaces dieses Bereichs an den Client (lib/i18n/message-scopes.ts).
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <AreaIntlProvider area="admin">{children}</AreaIntlProvider>;
}
