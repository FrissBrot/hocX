"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";

import { registerClientMessageTranslator } from "@/lib/i18n/client-messages";

// Stellt lib/i18n/client-messages.ts die Uebersetzungen der aktuellen UI-Sprache bereit.
export function ClientMessagesBridge() {
  const t = useTranslations("common.clientErrors");
  useEffect(() => {
    registerClientMessageTranslator((key, values) => t(key, values));
    return () => registerClientMessageTranslator(null);
  }, [t]);
  return null;
}
