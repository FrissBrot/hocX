"use client";

import { browserApiBaseUrl } from "@/lib/api/client";

/**
 * POST mit JSON-Body und Download der Antwort als Datei (Exporte mit Passwort im Body statt in der
 * URL). Wirft bei einem Fehler die Meldung des Backends (detail).
 */
export async function postAndDownload(path: string, body: unknown, fallbackFilename: string): Promise<void> {
  const res = await fetch(`${browserApiBaseUrl}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data.detail === "string") message = data.detail;
    } catch {
      // keine JSON-Antwort
    }
    throw new Error(message);
  }
  const blob = await res.blob();
  const disposition = res.headers.get("content-disposition") ?? "";
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
  const plain = /filename="?([^";]+)"?/i.exec(disposition)?.[1];
  const filename = encoded ? decodeURIComponent(encoded) : plain ?? fallbackFilename;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
