import { getTranslations } from "next-intl/server";

import { PublicShareGallery } from "@/components/share/public-share-gallery";
import { backendFetch } from "@/lib/api/client";
import { PublicShare } from "@/types/api";

// Öffentlich ohne Login erreichbar: proxy.ts nimmt /share/* vom Login-Redirect aus, der Token
// in der URL ist die einzige Authentifizierung (siehe backend public_share.py).
export default async function PublicSharePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const t = await getTranslations("share.publicPage");
  const share = await backendFetch<PublicShare>(`/api/public/share/${encodeURIComponent(token)}`);

  if (!share) {
    return (
      <main className="public-share-page public-share-page-center">
        <div className="card public-share-unavailable">
          <h1 className="page-title">{t("linkUnavailable")}</h1>
          <p className="muted">{t("linkUnavailableHint")}</p>
        </div>
      </main>
    );
  }

  return <PublicShareGallery share={share} />;
}
