import type { Metadata } from "next";
import { headers } from "next/headers";
import { getTranslations } from "next-intl/server";

import { VerifyCheck } from "@/components/verify-check";
import { getVerifySite } from "@/lib/api";
import { parseDocumentId } from "@/lib/verify";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("abgabebox.verify");
  return { title: t("title") };
}

// Öffentliche Prüfseite für PDFs aus hocX. Mit ?id= (QR-Code im PDF) zeigt sie nur die Kurz-ID
// des erwarteten Dokuments - Inhalte erst nach einem passenden Hash. Unter der Prüf-Domain eines
// Mandanten (verify.verein.ch) zeigt sie zusätzlich dessen Namen und Logo im Kopf.
export default async function VerifyPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  // Host der Anfrage (Traefik reicht ihn unverändert durch); nur er bestimmt die Prüf-Domain.
  const host = (await headers()).get("host") ?? "";
  const site = host ? await getVerifySite(host) : null;
  return <VerifyCheck documentId={parseDocumentId(params.id)} site={site?.tenant_name ? site : null} />;
}
