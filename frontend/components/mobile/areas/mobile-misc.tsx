"use client";

import { useRouter } from "next/navigation";
import type { Route } from "next";
import { useTranslations } from "next-intl";

import { useMobileSession, useOpenMore } from "@/components/mobile/mobile-shell";
import { MobileDesktopHint, MobileSubHeader } from "@/components/mobile/mobile-ui";
import { PhotosView } from "@/components/photos/photos-view";

/** Fotos: dieselbe Galerie wie am Desktop (Raster, Auswahl, Vollbild, Alben, Duplikate),
 * in der Mobile-Variante mit eigenem Kopf, Segment und Plus-Button. */
export function MobilePhotos() {
  const t = useTranslations("photos.view");
  const tMobile = useTranslations("mobile");
  const openMore = useOpenMore();
  return (
    <div className="mobile-page mobile-page-list mobile-photos">
      <MobileSubHeader title={t("pageTitle")} subtitle={t("description")} backLabel={tMobile("tabs.more")} onBack={openMore} />
      <div className="mobile-section mobile-embedded">
        <PhotosView mobile />
      </div>
    </div>
  );
}

/** Bereiche, die bewusst am Computer bleiben (Element-Editor, Dokument-Layouts, Import):
 * mobil ein klarer Hinweis statt einer halb bedienbaren Desktop-Ansicht. */
export function MobileDesktopOnly({ navKey, backHref, backNavKey }: { navKey: string; backHref?: string; backNavKey?: string }) {
  const tMobile = useTranslations("mobile");
  const tNav = useTranslations("nav");
  const router = useRouter();
  const openMore = useOpenMore();
  const session = useMobileSession();
  return (
    <div className="mobile-page">
      <MobileSubHeader
        title={tNav(navKey)}
        backLabel={backNavKey ? tNav(backNavKey) : tMobile("tabs.more")}
        onBack={backHref ? () => router.push(backHref as Route) : openMore}
      />
      <div className="mobile-section">
        <MobileDesktopHint text={tMobile("common.desktopOnly")} email={session?.user?.email} />
      </div>
    </div>
  );
}
