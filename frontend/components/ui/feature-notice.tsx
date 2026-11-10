import { getTranslations } from "next-intl/server";

import { StatusBanner } from "@/components/ui/status-banner";
import type { FeatureCode } from "@/lib/features.generated";
import type { FeatureAccess } from "@/lib/permissions";

/** Hinweis auf einer Seite, deren Abo-Feature (permissions/features.json) nicht voll gebucht ist:
 * nach einem Downgrade nur lesend oder im Abo nicht enthalten. Server Component. */
export async function FeatureNotice({ feature, access }: { feature: FeatureCode; access: FeatureAccess }) {
  if (access === "full") return null;
  const t = await getTranslations("common");
  const name = t(`features.${feature}`);
  return <StatusBanner tone="neutral" message={access === "read_only" ? t("featureNotice.readOnly", { name }) : t("featureNotice.notBooked", { name })} />;
}
