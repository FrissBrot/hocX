import { TemplateLibrary } from "@/components/documents/template-library";
import { StudioPage } from "@/components/documents/studio-page";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import type { Capabilities } from "@/lib/documents/api";

// Protokollgestaltung: gemeinsame Gestaltung der Sitzungsdokumente (Protokoll, Einladung …),
// gilt für alle Protokollvorlagen ohne eigene Gestaltung.
export default async function Page() {
  const session = await requireSession();
  const capabilities = await backendFetchWithSession<Capabilities>("/api/document-studio/capabilities");
  return (
    <StudioPage session={session} activeHref="/documents/protocols">
      {capabilities ? <TemplateLibrary capabilities={capabilities} scope="session" /> : null}
    </StudioPage>
  );
}
