import { AreaIntlProvider } from "@/components/i18n/area-intl-provider";
import "@/app/styles/file-import.css";

// Datei-Import (Wizard): eigene Namespaces, Dateien-Styles kommen aus app/files/layout.tsx.
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <AreaIntlProvider area="fileImport">{children}</AreaIntlProvider>;
}
