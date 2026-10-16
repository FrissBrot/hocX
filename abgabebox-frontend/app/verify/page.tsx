import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { VerifyCheck } from "@/components/verify-check";
import { parseDocumentId } from "@/lib/verify";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("abgabebox.verify");
  return { title: t("title") };
}

// Öffentliche Prüfseite für PDFs aus hocX. Mit ?id= (QR-Code im PDF) zeigt sie nur die Kurz-ID
// des erwarteten Dokuments - Inhalte erst nach einem passenden Hash.
export default async function VerifyPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  return <VerifyCheck documentId={parseDocumentId(params.id)} />;
}
