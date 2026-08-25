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
        cache: "no-store"
      });

      if (!response.ok) {
        console.error(`[backendFetch] ${init?.method ?? "GET"} ${path} → HTTP ${response.status}`);
        return null;
      }

      return (await response.json()) as T;
    } catch (err) {
      if (attempt === 0) continue;
      console.error(`[backendFetch] ${init?.method ?? "GET"} ${path} → network error:`, err);
      return null;
    }
  }
  return null;
}

export async function browserApiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  if (typeof navigator !== "undefined" && !navigator.onLine) throw new ApiError("Keine Internetverbindung", "offline");
  let response: Response;
  try {
    response = await fetch(`${publicApiUrl}${path}`, {
      ...init,
      signal: init?.signal ?? AbortSignal.timeout(15_000),
      credentials: "include",
      headers: isFormData ? init?.headers : { "Content-Type": "application/json", ...(init?.headers ?? {}) }
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") throw new ApiError("Zeitüberschreitung beim Server", "timeout");
    throw new ApiError("Backend nicht erreichbar", "backend");
  }

  if (!response.ok) {
    const text = await response.text();
    let message = text || `Request failed with status ${response.status}`;
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
    const kind = response.status === 401 || response.status === 403 ? "auth"
      : response.status === 409 ? "conflict"
      : response.status >= 500 ? "backend" : "validation";
    throw new ApiError(message, kind, response.status);
  }

  if (response.status === 204 || response.headers.get("content-length") === "0") {
    return null as T;
  }
  return (await response.json()) as T;
}
