import { AreaIntlProvider } from "@/components/i18n/area-intl-provider";

// Rechtstexte: eigener Bereich, damit der Namespace "legal" nur hier und nicht auf der
// Startseite der Website mitgeliefert wird (lib/i18n/message-scopes.ts).
export default function WebsiteLegalLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <AreaIntlProvider area="websiteLegal">{children}</AreaIntlProvider>;
}
