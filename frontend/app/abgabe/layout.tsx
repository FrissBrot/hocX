import { AreaIntlProvider } from "@/components/i18n/area-intl-provider";

// Öffentliche Seite «Meine Abgabe» (persönlicher Link, ohne Login): eigene Übersetzungen.
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <AreaIntlProvider area="submissionAccess">{children}</AreaIntlProvider>;
}
