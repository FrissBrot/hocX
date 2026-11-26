import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { LegalPage } from "@/components/website/legal-page";

// Öffentlich unter https://<website-domain>/terms (proxy.ts schreibt auf /website/terms um, ohne
// Sitzungsprüfung). Text: messages/<locale>/legal.json, siehe components/website/legal-page.tsx.

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("legal.terms.meta");
  return { title: t("title"), description: t("description") };
}

export default function WebsiteTermsPage() {
  return <LegalPage kind="terms" />;
}
