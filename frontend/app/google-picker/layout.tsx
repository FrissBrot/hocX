import { AreaIntlProvider } from "@/components/i18n/area-intl-provider";
import "@/app/styles/file-import.css";

// Google Picker des Datei-Imports: nur auf der eigenen Origin CLOUD_IMPORT_PICKER_DOMAIN erreichbar
// (proxy.ts), dort ohne hocX-Sitzung und als einzige Seite mit gelockerter CSP (lib/csp.ts).
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <AreaIntlProvider area="fileImport">{children}</AreaIntlProvider>;
}
