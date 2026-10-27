"use client";

// Hinweis oben im Designer: wen eine Änderung an dieser Gestaltung trifft, bevor jemand
// veröffentlicht (Sitzungsdokumente: Protokoll, Einladung, Traktandenliste).

import { useMemo } from "react";
import { useLocale, useTranslations } from "next-intl";

import type { DocumentTemplateInfo } from "@/lib/documents/api";

export type DetachAction = { label: string; run: () => void };

type Props = { template: DocumentTemplateInfo; embedded: boolean; onDetach?: DetachAction | null };

export function DesignUsageBanner({ template, embedded, onDetach }: Props) {
  const t = useTranslations("documentStudio.usage");
  const locale = useLocale();
  const listFormat = useMemo(() => new Intl.ListFormat(locale, { style: "long", type: "conjunction" }), [locale]);
  const users = template.used_in ?? [];
  const shared = users.length > 1 || (template.is_default && users.length > 0);
  // Eingebettet im Vorlagen-Editor zeigt die Zuweisungs-Leiste die alleinige Verwendung schon
  if (!shared && embedded) return null;
  if (shared) {
    return (
      <div className="studio-usage-banner studio-usage-banner-warning" role="note">
        <span>
          {t("shared", { count: users.length, names: listFormat.format(users.map((ref) => ref.name)) })}
          {template.is_default ? ` ${t("default")}` : ""}
        </span>
        {onDetach ? (
          <button type="button" className="button-secondary" onClick={onDetach.run}>
            {onDetach.label}
          </button>
        ) : null}
      </div>
    );
  }
  return (
    <div className="studio-usage-banner" role="note">
      <span>{users.length === 1 ? t("single", { name: users[0].name }) : t("unused")}</span>
    </div>
  );
}
