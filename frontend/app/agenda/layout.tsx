import { AreaIntlProvider } from "@/components/i18n/area-intl-provider";

// Liefert die Uebersetzungs-Namespaces dieses Bereichs an den Client (lib/i18n/message-scopes.ts).
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <AreaIntlProvider area="agenda">{children}</AreaIntlProvider>;
}
