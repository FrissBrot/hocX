import { AreaIntlProvider } from "@/components/i18n/area-intl-provider";
import "@/app/styles/documents.css";
import "@/app/styles/media.css";
import "@/app/styles/studio.css";
import "@/app/styles/uploads.css";

// Liefert die Uebersetzungs-Namespaces dieses Bereichs an den Client (lib/i18n/message-scopes.ts).
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <AreaIntlProvider area="documents">{children}</AreaIntlProvider>;
}
