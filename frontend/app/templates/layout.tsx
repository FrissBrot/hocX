import { AreaIntlProvider } from "@/components/i18n/area-intl-provider";
import "@/app/styles/block-config.css";
import "@/app/styles/element-editor.css";
import "@/app/styles/studio.css";
import "@/app/styles/templates.css";

// Liefert die Uebersetzungs-Namespaces dieses Bereichs an den Client (lib/i18n/message-scopes.ts).
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <AreaIntlProvider area="templates">{children}</AreaIntlProvider>;
}
