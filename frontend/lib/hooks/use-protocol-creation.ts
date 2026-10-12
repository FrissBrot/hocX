"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";

type Names = { protocol_number: string | null; title: string | null };

export function useProtocolCreation(open: boolean, templateId: string, protocolDate: string) {
  const t = useTranslations("protocols.builder");
  const showToast = useToast();
  const [result, setResult] = useState<{ key: string; names?: Names; error?: string } | null>(null);
  const key = `${templateId}:${protocolDate}`;
  const previewFailed = t("previewFailed");
  const saves = useRef<Promise<unknown>>(Promise.resolve());

  useEffect(() => {
    if (!open || !templateId || !protocolDate) return;
    const controller = new AbortController();
    setResult(null);
    const timer = setTimeout(() => {
      const query = new URLSearchParams({ template_id: templateId, protocol_date: protocolDate });
      void browserApiFetch<Names>(`/api/protocols/preview?${query}`, { signal: controller.signal })
        .then((names) => { if (!controller.signal.aborted) setResult({ key, names }); })
        .catch((error) => {
          if (!controller.signal.aborted) setResult({ key, error: error instanceof Error ? error.message : previewFailed });
        });
    }, 150);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [open, templateId, protocolDate, key, previewFailed]);

  function rememberTemplate(id: string) {
    // Die Reihenfolge bleibt auch bei schnellem Wechsel der Auswahl erhalten.
    saves.current = saves.current.then(() => browserApiFetch("/api/protocols/template-preference", {
      method: "PUT", body: JSON.stringify({ template_id: id || null }),
    })).catch((error) => {
      showToast(error instanceof Error ? error.message : t("templateSaveFailed"), "error");
    });
  }

  const current = open && result?.key === key ? result : null;
  return { preview: current?.names ?? null, previewMessage: current?.error ?? t("previewLoading"), rememberTemplate };
}
