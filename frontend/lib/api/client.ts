import { clientMessage } from "@/lib/i18n/client-messages";

const internalApiUrl = process.env.INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
// Browser-seitige Aufrufe laufen immer same-origin (relative Pfade), damit sie auf jeder
// Domain (Hauptdomain oder Mandanten-Custom-Domain) automatisch gegen die richtige Origin
// gehen und das dort gescopte Session-Cookie mitgeschickt wird.
const publicApiUrl = "";
export const browserApiBaseUrl = publicApiUrl;

export class ApiError extends Error {
  constructor(message: string, public readonly kind: "offline" | "timeout" | "backend" | "auth" | "validation" | "conflict", public readonly status?: number) {
    super(message);
  }
}

// Obergrenze fuer serverseitige Backend-Aufrufe aus Server-Components (Audit MAIN-FE-002).
export const SERVER_FETCH_TIMEOUT_MS = 30_000;
// Standard-Timeout fuer Browser-Aufrufe und die laengere Variante fuer Endpunkte, die serverseitig
// lange arbeiten (LaTeX-PDF-Export, Word-/CSV-/Katalog-Import, Mandanten-Klon). Mit dem Standard
// brach der Client nach 15 s ab, waehrend der Server die Aktion erfolgreich zu Ende fuehrte -
// Fehlermeldung trotz Erfolg und doppelte Importe bei Wiederholung (Audit MAIN-FE-004).
export const DEFAULT_BROWSER_TIMEOUT_MS = 15_000;
export const LONG_RUNNING_TIMEOUT_MS = 5 * 60_000;

export type BrowserApiFetchInit = RequestInit & { timeoutMs?: number };

export async function backendFetch<T>(path: string, init?: RequestInit): Promise<T | null> {
  // Not shared with abgabebox-frontend/lib/api.ts's fetchJson (see that file's comment,
  // audit finding E-Niedrig-4): that app's public endpoints need neither the session-cookie
  // forwarding nor the retry below, so keeping them separate avoids forcing a shared
  // package on two otherwise-independently-deployed Next.js apps.
  // Ein einzelner Retry bei einem echten Netzwerkfehler (nicht bei einer regulären HTTP-
  // Fehlerantwort): Node's fetch-Verbindungspool zum Backend-Container reused Sockets, die das
  // Backend zeitgleich schon als idle geschlossen haben kann ("ECONNRESET"/"socket hang up") -
  // das war die Ursache eines Login-Loops, weil requireSession() ein fehlgeschlagenes
  // Session-Fetch bisher wie "nicht eingeloggt" behandelt hat. Ein Retry mit frischer Verbindung
  // behebt diese Klasse von Fehlern zuverlässig, ohne echte Auth-Fehler zu verschleiern.
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const response = await fetch(`${internalApiUrl}${path}`, {
        ...init,
        // Ohne Timeout blockierte ein haengendes (nicht ablehnendes) Backend jeden Seiten-Render
        // bis zum undici-Default von ~300 s (Audit MAIN-FE-002).
        signal: init?.signal ?? AbortSignal.timeout(SERVER_FETCH_TIMEOUT_MS),
        cache: "no-store"
      });

      if (!response.ok) {
        console.error(`[backendFetch] ${init?.method ?? "GET"} ${path} → HTTP ${response.status}`);
        return null;
      }

      return (await response.json()) as T;
    } catch (err) {
      // Retry nur fuer echte Verbindungsfehler; ein Timeout wuerde die Wartezeit nur verdoppeln.
      const timedOut = err instanceof DOMException && err.name === "TimeoutError";
      if (attempt === 0 && !timedOut) continue;
      console.error(`[backendFetch] ${init?.method ?? "GET"} ${path} → network error:`, err);
      return null;
    }
  }
  return null;
}

export async function browserApiFetch<T>(path: string, options?: BrowserApiFetchInit): Promise<T> {
  const { timeoutMs, ...init } = options ?? {};
  const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
  if (typeof navigator !== "undefined" && !navigator.onLine) throw new ApiError(clientMessage("offline"), "offline");
  let response: Response;
  try {
    response = await fetch(`${publicApiUrl}${path}`, {
      ...init,
      signal: init.signal ?? AbortSignal.timeout(timeoutMs ?? DEFAULT_BROWSER_TIMEOUT_MS),
      credentials: "include",
      headers: isFormData ? init.headers : { "Content-Type": "application/json", ...(init.headers ?? {}) }
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") throw new ApiError(clientMessage("timeout"), "timeout");
    throw new ApiError(clientMessage("unreachable"), "backend");
  }

  if (!response.ok) throw errorFromResponse(response.status, await response.text());

  if (response.status === 204 || response.headers.get("content-length") === "0") {
    return null as T;
  }
  return (await response.json()) as T;
}

function errorFromResponse(status: number, text: string): ApiError {
  let message = text || `Request failed with status ${status}`;
  try {
    const json = JSON.parse(text);
    if (json?.detail) {
      if (typeof json.detail === "string") {
        message = json.detail;
      } else if (Array.isArray(json.detail)) {
        message = json.detail
          .map((e: { msg?: string; loc?: string[] }) => {
            const field = e.loc ? e.loc.filter((l) => l !== "body").join(".") : null;
            return field ? `${field}: ${e.msg ?? e}` : (e.msg ?? String(e));
          })
          .join(" · ");
      }
    }
  } catch {
    // keep raw text if not parseable JSON
  }
  const kind = status === 401 || status === 403 ? "auth"
    : status === 409 ? "conflict"
    : status >= 500 ? "backend" : "validation";
  return new ApiError(message, kind, status);
}

// POSTs a FormData body like browserApiFetch, but over XMLHttpRequest: fetch() has no
// upload-progress events, and for a multi-GB ZIP the user needs to see how far the byte
// transfer has got. Same error mapping as browserApiFetch.
export function browserApiUpload<T>(
  path: string,
  body: FormData,
  options: { timeoutMs: number; onProgress?: (loaded: number, total: number) => void; signal?: AbortSignal },
): Promise<T> {
  if (typeof navigator !== "undefined" && !navigator.onLine) return Promise.reject(new ApiError(clientMessage("offline"), "offline"));
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${publicApiUrl}${path}`);
    xhr.withCredentials = true;
    xhr.timeout = options.timeoutMs;
    if (options.onProgress) {
      const onProgress = options.onProgress;
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(event.loaded, event.total);
      };
    }
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(errorFromResponse(xhr.status, xhr.responseText));
        return;
      }
      if (xhr.status === 204 || !xhr.responseText) {
        resolve(null as T);
        return;
      }
      try {
        resolve(JSON.parse(xhr.responseText) as T);
      } catch {
        reject(new ApiError(clientMessage("invalidResponse"), "backend", xhr.status));
      }
    };
    xhr.ontimeout = () => reject(new ApiError(clientMessage("timeout"), "timeout"));
    xhr.onerror = () => reject(new ApiError(clientMessage("unreachable"), "backend"));
    xhr.onabort = () => reject(new DOMException("Upload abgebrochen", "AbortError"));
    if (options.signal) {
      if (options.signal.aborted) {
        xhr.abort();
        return;
      }
      options.signal.addEventListener("abort", () => xhr.abort(), { once: true });
    }
    xhr.send(body);
  });
}
