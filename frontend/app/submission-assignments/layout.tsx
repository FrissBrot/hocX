import { AreaIntlProvider } from "@/components/i18n/area-intl-provider";
import "@/app/styles/block-config.css";
import "@/app/styles/submissions.css";
import "@/app/styles/uploads.css";

// Liefert die Uebersetzungs-Namespaces dieses Bereichs an den Client (lib/i18n/message-scopes.ts).
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <AreaIntlProvider area="submissionAssignments">{children}</AreaIntlProvider>;
}
