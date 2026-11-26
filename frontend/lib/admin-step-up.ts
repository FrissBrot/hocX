"use client";

import { ApiError, browserApiBaseUrl, browserApiFetch, type BrowserApiFetchInit } from "@/lib/api/client";
import { getPasskeyAssertion } from "@/lib/webauthn";
import type { PasskeyAssertionStart } from "@/types/api";

// Frische Passkey-Bestätigung für kritische Admin-Aktionen (backend app/core/admin_step_up.py,
// Security-Review M2/L7). Die Bestätigung gilt nur für genau diese Anfrage: Zweck, Methode, Pfad und
// SHA-256 des Bodys werden beim Start mitgegeben, die Assertion geht im Header X-Hocx-Step-Up mit.

export type StepUpPurpose =
  | "passkey-manage"
  | "admin-manage"
  | "tenant-delete"
  | "tenant-export"
  | "storage-destructive"
  | "backup-restore"
  | "backup-settings"
  | "catalog-change"
  | "user-mfa-reset"
  | "user-manage"
  | "platform-settings"
  | "user-credentials"
  | "tenant-import"
  | "security-block"
  | "security-export"
  | "security-resolve"
  | "cloud-import-cancel"
  | "security-incident";

export const STEP_UP_HEADER = "X-Hocx-Step-Up";

async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function base64url(text: string): string {
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Header für eine Admin-Anfrage mit Passkey-Bestätigung. `path` ohne Query, `body` genau der Text,
 * der gesendet wird (leer = kein Body). */
export async function stepUpHeaders(purpose: StepUpPurpose, method: string, path: string, body = ""): Promise<Record<string, string>> {
  const start = await browserApiFetch<PasskeyAssertionStart>("/api/admin/mfa/step-up/start", {
    method: "POST",
    body: JSON.stringify({ purpose, method: method.toUpperCase(), path, body_sha256: await sha256Hex(body) }),
  });
  const credential = await getPasskeyAssertion(start.public_key);
  return { [STEP_UP_HEADER]: base64url(JSON.stringify({ flow_token: start.flow_token, credential })) };
}

/** browserApiFetch mit vorheriger Passkey-Bestätigung (Body als String, wie er gesendet wird). */
export async function stepUpFetch<T>(
  purpose: StepUpPurpose,
  path: string,
  init: BrowserApiFetchInit & { method: string; body?: string }
): Promise<T> {
  const headers = await stepUpHeaders(purpose, init.method, path, init.body ?? "");
  return browserApiFetch<T>(path, { ...init, headers: { ...(init.headers as Record<string, string> | undefined), ...headers } });
}

/** Datei-Download (POST) mit Passkey-Bestätigung: Antwort als Blob, Dateiname aus
 * Content-Disposition. Fehlertext aus dem Backend (detail.message bzw. detail). */
export async function stepUpDownload(purpose: StepUpPurpose, path: string, body: string, fallbackName: string): Promise<void> {
  const headers = await stepUpHeaders(purpose, "POST", path, body);
  const response = await fetch(`${browserApiBaseUrl}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...headers },
    body,
  });
  if (!response.ok) {
    const text = await response.text();
    let message = `HTTP ${response.status}`;
    try {
      const detail = JSON.parse(text)?.detail;
      message = typeof detail === "string" ? detail : typeof detail?.message === "string" ? detail.message : message;
    } catch {
      // kein JSON: Statuscode genügt
    }
    throw new ApiError(message, response.status === 403 || response.status === 401 ? "auth" : "backend", response.status);
  }
  const blob = await response.blob();
  const match = /filename="?([^";]+)"?/i.exec(response.headers.get("content-disposition") ?? "");
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = match?.[1] ?? fallbackName;
  anchor.click();
  URL.revokeObjectURL(url);
}
