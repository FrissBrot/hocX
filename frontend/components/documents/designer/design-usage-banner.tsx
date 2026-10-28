"use client";

// Hinweis oben im Designer: wen eine Änderung an dieser Gestaltung trifft, bevor jemand
// veröffentlicht (Sitzungsdokumente: Protokoll, Einladung, Traktandenliste). Lässt sich
// wegklicken; das gilt pro Gestaltung und Verwendung (nur in diesem Browser) und der Hinweis
// erscheint wieder, sobald sich die Verwendung ändert.

import { useEffect, useMemo, useState } from "react";
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
  const dismissKey = `hocx.designUsageDismissed.${template.id}`;
  const signature = `${template.is_default ? "d" : ""}:${users.map((ref) => ref.id).sort().join(",")}`;
  const [dismissed, setDismissed] = useState(false);

  // Erst nach dem Mounten lesen (kein Unterschied zwischen Server- und Client-Render)
  useEffect(() => {
    try {
      setDismissed(window.localStorage.getItem(dismissKey) === signature);
    } catch {
      setDismissed(false);
    }
  }, [dismissKey, signature]);

  function dismiss() {
    setDismissed(true);
    try {
      window.localStorage.setItem(dismissKey, signature);
    } catch {
      // Ohne Speicher bleibt der Hinweis nur bis zum Neuladen ausgeblendet
    }
  }

  // Eingebettet im Vorlagen-Editor zeigt die Zuweisungs-Leiste die alleinige Verwendung schon
  if (dismissed || (!shared && embedded)) return null;
  const dismissButton = (
    <button type="button" className="button-icon-soft button-icon-soft-sm studio-usage-banner-dismiss" aria-label={t("dismiss")} title={t("dismiss")} onClick={dismiss}>
      ✕
    </button>
  );
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
        {dismissButton}
      </div>
    );
  }
  return (
    <div className="studio-usage-banner" role="note">
      <span>{users.length === 1 ? t("single", { name: users[0].name }) : t("unused")}</span>
      {dismissButton}
    </div>
  );
}
