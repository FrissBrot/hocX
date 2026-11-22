import { AreaIntlProvider } from "@/components/i18n/area-intl-provider";
import "@/app/styles/photos.css";

// Upload-Verlauf der Ablage: das Vorgangsdetail bettet das Fotoraster ein (Fotos-Styles und -Texte);
// Dateien-Styles kommen aus app/files/layout.tsx.
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <AreaIntlProvider area="fileUploads">{children}</AreaIntlProvider>;
}
