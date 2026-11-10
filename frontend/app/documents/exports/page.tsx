import { ExportHistory } from "@/components/documents/export-history";
import { StudioPage } from "@/components/documents/studio-page";
import { requireSession } from "@/lib/api/server";

// Export-Verlauf: kein eigener Tab, erreichbar über die Dokumentvorlagen (aktiver Tab dort).
export default async function Page() {
  const session = await requireSession();
  return (
    <StudioPage session={session} activeHref="/documents">
      <ExportHistory />
    </StudioPage>
  );
}
