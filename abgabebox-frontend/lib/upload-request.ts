// Upload per XMLHttpRequest statt fetch: nur XHR meldet den Sende-Fortschritt
// (`upload.onprogress`), fetch kennt für Request-Bodies keinen Fortschritt. Das Ergebnis wird als
// gewöhnliches `Response`-Objekt zurückgegeben, damit upload-form.tsx die bestehende Auswertung
// (Status, Retry-After, JSON-Body, 401/429/503) unverändert weiterverwenden kann.
//
// Verhalten wie fetch: Netzwerkfehler → TypeError, Zeitüberschreitung → DOMException
// "TimeoutError" (wie AbortSignal.timeout), jede HTTP-Antwort (auch 4xx/5xx) wird aufgelöst.

export type UploadPhase = { phase: "uploading"; percent: number } | { phase: "processing" };

type XhrLike = Pick<
  XMLHttpRequest,
  "open" | "send" | "abort" | "status" | "responseText" | "getAllResponseHeaders" | "timeout" | "onload" | "onerror" | "ontimeout" | "onabort"
> & { upload: Pick<XMLHttpRequestUpload, "onprogress" | "onload"> };

export type SendUploadOptions = {
  timeoutMs: number;
  onPhase?: (phase: UploadPhase) => void;
  // Nur für Tests: eigene XHR-Implementierung einschleusen
  createXhr?: () => XhrLike;
};

/** Prozentwert 0–100 aus übertragenen Bytes; ohne bekannte Gesamtgrösse 0. */
export function uploadPercent(loaded: number, total: number): number {
  if (!Number.isFinite(total) || total <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((loaded / total) * 100)));
}

/** Zerlegt `getAllResponseHeaders()` (CRLF-getrennt, "Name: Wert") in ein Headers-Objekt. */
export function parseResponseHeaders(raw: string): Headers {
  const headers = new Headers();
  for (const line of raw.trim().split(/[\r\n]+/)) {
    const index = line.indexOf(":");
    if (index <= 0) continue;
    try {
      headers.append(line.slice(0, index).trim(), line.slice(index + 1).trim());
    } catch {
      // ungültiger Header-Name: ignorieren, für die Auswertung irrelevant
    }
  }
  return headers;
}

// Statuscodes ohne Body (Response-Konstruktor lehnt einen Body dafür ab)
const NULL_BODY_STATUS = new Set([101, 204, 205, 304]);

export function sendUpload(url: string, body: FormData, { timeoutMs, onPhase, createXhr }: SendUploadOptions): Promise<Response> {
  return new Promise<Response>((resolve, reject) => {
    const xhr = createXhr ? createXhr() : new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.timeout = timeoutMs;
    onPhase?.({ phase: "uploading", percent: 0 });
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onPhase?.({ phase: "uploading", percent: uploadPercent(event.loaded, event.total) });
      }
    };
    // Alle Bytes sind beim Server: ab jetzt wartet die Seite auf Prüfung und Ablage.
    xhr.upload.onload = () => {
      onPhase?.({ phase: "processing" });
    };
    xhr.onload = () => {
      const status = xhr.status;
      if (status < 200 || status > 599) {
        reject(new TypeError("Upload: unerwarteter Status")); // i18n-ok: nur intern, upload-form zeigt eigene Meldung
        return;
      }
      resolve(new Response(NULL_BODY_STATUS.has(status) ? null : xhr.responseText, {
        status,
        headers: parseResponseHeaders(xhr.getAllResponseHeaders()),
      }));
    };
    xhr.onerror = () => reject(new TypeError("Upload: Netzwerkfehler")); // i18n-ok: nur intern, upload-form zeigt eigene Meldung
    xhr.onabort = () => reject(new DOMException("Upload abgebrochen", "AbortError")); // i18n-ok: nur intern
    xhr.ontimeout = () => reject(new DOMException("Upload: Zeitüberschreitung", "TimeoutError")); // i18n-ok: nur intern
    xhr.send(body);
  });
}
