"use client";

import { useLocale, useTranslations } from "next-intl";

import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { ApiError, browserApiFetch } from "@/lib/api/client";
import { toIntlLocale } from "@/lib/utils/format";
import type { ProtocolSummary, ProtocolTemplateSyncResult } from "@/types/api";

/** Bekannte englische Backend-Meldungen in Benutzersprache, sonst die Meldung selbst. */
export function protocolActionError(error: unknown, t: (key: string) => string, fallback: string): string {
  if (error instanceof ApiError && error.status === 409 && /already abgeschlossen/i.test(error.message)) {
    return t("alreadyFinalizedError");
  }
  const code = error instanceof ApiError && error.status === 409 ? (error.detail as { code?: string } | undefined)?.code : undefined;
  if (code === "protocol_has_fines") {
    return t("deleteHasFinesError");
  }
  if (code === "protocol_has_collected_fines") {
    return t("deleteHasCollectedFinesError");
  }
  return error instanceof Error && error.message ? error.message : fallback;
}

/** Status, in denen ein Protokoll auf eine geänderte Vorlage hinweist (noch nicht durchgeführt). */
const TEMPLATE_HINT_STATUSES = new Set(["geplant", "vorbereitet"]);

/** Ob die Vorlage seit dem Erstellen bzw. letzten Abgleich des Protokolls geändert wurde. */
export function templateChangedSinceSync(protocol: Pick<ProtocolSummary, "status" | "template_version" | "template_latest_version">): boolean {
  return (
    TEMPLATE_HINT_STATUSES.has(protocol.status) &&
    protocol.template_latest_version != null &&
    protocol.template_version != null &&
    protocol.template_latest_version > protocol.template_version
  );
}

/** Elemente eines Protokolls aus der aktuellen Vorlage neu aufbauen (erfasste Daten bleiben).
 * Erst eine Vorschau (dry_run) als Rückfrage, damit klar ist, was hinzukommt, wegfällt oder
 * stehen bleibt. Liefert true, wenn abgeglichen wurde. Genutzt von der Protokollliste und vom
 * Hinweis «Vorlage wurde geändert» im Protokollkopf. */
export function useTemplateSync() {
  const t = useTranslations("protocols.builder");
  const locale = useLocale();
  const confirm = useConfirm();
  const showToast = useToast();

  return async function syncWithTemplate(protocolId: string): Promise<boolean> {
    const url = `/api/protocols/${protocolId}/sync-template`;
    try {
      const preview = await browserApiFetch<ProtocolTemplateSyncResult>(`${url}?dry_run=true`, { method: "POST" });
      const listFormat = new Intl.ListFormat(toIntlLocale(locale), { style: "long", type: "conjunction" });
      const message = [
        t("syncTemplateConfirmMessage", {
          updated: preview.updated_elements.length,
          added: preview.added_elements.length,
          removed: preview.removed_elements.length,
        }),
        preview.removed_elements.length
          ? t("syncTemplateConfirmRemoved", { names: listFormat.format(preview.removed_elements) })
          : null,
        preview.kept_elements.length
          ? t("syncTemplateConfirmKept", { count: preview.kept_elements.length, names: listFormat.format(preview.kept_elements) })
          : null,
      ]
        .filter(Boolean)
        .join(" ");
      const ok = await confirm({
        title: t("syncTemplateConfirmTitle"),
        message,
        confirmLabel: t("syncTemplateConfirmLabel"),
      });
      if (!ok) return false;
      await browserApiFetch<ProtocolTemplateSyncResult>(url, { method: "POST" });
      showToast(t("syncTemplateDone"), "success");
      return true;
    } catch (error) {
      showToast(protocolActionError(error, t, t("syncTemplateFailed")), "error");
      return false;
    }
  };
}
