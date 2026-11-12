"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";

import { useConfirm } from "@/contexts/confirm-context";
import { browserApiFetch } from "@/lib/api/client";

export type EventDeleteImpact = { submission_count: number; file_count: number };

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

/** Text der Löschrückfrage: was verloren geht (Abgabe-Einreichungen samt Dateien) und die Alternative «absagen». */
export function eventDeleteMessage(t: TFunc, impact: EventDeleteImpact | null, title?: string | null): string {
  const parts = [title ? t("deleteDialog.messageWithTitle", { title }) : t("deleteDialog.message")];
  if (impact === null) {
    parts.push(t("deleteDialog.submissionsUnknown"));
  } else if (impact.submission_count > 0) {
    parts.push(t("deleteDialog.submissions", { count: impact.submission_count, files: impact.file_count }));
  }
  parts.push(t("deleteDialog.cancelInstead"));
  return parts.join(" ");
}

/**
 * Rückfrage vor dem Löschen eines Termins. Fragt zuerst beim Backend nach, wie viele
 * Abgabe-Einreichungen und Dateien mitgelöscht würden (Kaskade), und nennt die Anzahl.
 */
export function useConfirmEventDelete() {
  const confirm = useConfirm();
  const t = useTranslations("events");
  return useCallback(
    async (eventId: string, title?: string | null): Promise<boolean> => {
      let impact: EventDeleteImpact | null = null;
      try {
        impact = await browserApiFetch<EventDeleteImpact>(`/api/events/${eventId}/delete-impact`);
      } catch {
        // Ohne Anzahl trotzdem warnen (allgemeiner Hinweis statt Zahl).
        impact = null;
      }
      return confirm({
        title: t("deleteDialog.title"),
        message: eventDeleteMessage(t, impact, title),
        tone: "danger",
        confirmLabel: t("toasts.deleteConfirmLabel"),
      });
    },
    [confirm, t]
  );
}
