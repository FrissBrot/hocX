import { AssetLibrary } from "@/components/documents/asset-library";
import { StudioPage } from "@/components/documents/studio-page";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import type { Capabilities } from "@/lib/documents/api";

export default async function Page() {
  const session = await requireSession();
  const capabilities = await backendFetchWithSession<Capabilities>("/api/document-studio/capabilities");
  return (
    <StudioPage session={session} activeHref="/documents/assets">
      {capabilities ? <AssetLibrary capabilities={capabilities} /> : null}
    </StudioPage>
  );
}
