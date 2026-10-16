// Laden und Erzeugen des FriendlyCaptcha-Widgets (selbst gehostetes Modul-Skript unter public/).
//
// Das Vendor-Skript initialisiert `.frc-captcha`-Elemente nur ein einziges Mal beim Laden
// (`DOMContentLoaded` bzw. sofort) und beobachtet das DOM danach nicht mehr. Jedes spaeter
// gemountete Widget - Client-Navigation zum naechsten Element, Neustart nach abgelaufenem
// Sitzungs-Token - bekaeme sonst nie eine Challenge, und die Abgabe bliebe auf "Sicherheitscheck
// laeuft" stehen. Deshalb wird jedes Widget hier explizit ueber `WidgetInstance` erzeugt und beim
// Unmount wieder zerstoert. Das Host-Element traegt `data-attached`, damit die Auto-Initialisierung
// des Skripts (falls es erst nach dem Mount fertig laedt) es nicht ein zweites Mal belegt.

export const FRIENDLY_CAPTCHA_SCRIPT_SRC = "/friendly-challenge.module.min.js";
export const FRIENDLY_CAPTCHA_SCRIPT_ID = "friendly-captcha-script";
export const FRIENDLY_CAPTCHA_PUZZLE_ENDPOINT = "https://api.friendlycaptcha.com/api/v1/puzzle";

export type FriendlyCaptchaWidget = {
  destroy: () => void;
  reset: () => void;
};

export type FriendlyCaptchaWidgetOptions = {
  sitekey: string;
  language: string;
  startMode: "auto" | "focus" | "none";
  puzzleEndpoint: string;
  doneCallback: (solution: string) => void;
  errorCallback: (error: unknown) => void;
};

export type FriendlyChallengeApi = {
  WidgetInstance: new (element: HTMLElement, options: FriendlyCaptchaWidgetOptions) => FriendlyCaptchaWidget;
};

type CaptchaWindow = { friendlyChallenge?: FriendlyChallengeApi };

let loadPromise: Promise<FriendlyChallengeApi> | null = null;

function currentApi(win: CaptchaWindow): FriendlyChallengeApi | null {
  return win.friendlyChallenge && typeof win.friendlyChallenge.WidgetInstance === "function" ? win.friendlyChallenge : null;
}

// Laedt das Modul-Skript genau einmal pro Dokument und liefert die globale API, sobald sie
// verfuegbar ist. Schlaegt das Laden fehl, wird der Cache verworfen, damit ein spaeterer Mount
// (z.B. nach Neustart des Checks) es erneut versuchen kann.
export function loadFriendlyChallenge(doc: Document = document, win: CaptchaWindow = window as unknown as CaptchaWindow): Promise<FriendlyChallengeApi> {
  const ready = currentApi(win);
  if (ready) return Promise.resolve(ready);
  if (loadPromise) return loadPromise;

  loadPromise = new Promise<FriendlyChallengeApi>((resolve, reject) => {
    let script = doc.getElementById(FRIENDLY_CAPTCHA_SCRIPT_ID) as HTMLScriptElement | null;
    const onLoad = () => {
      const api = currentApi(win);
      if (api) resolve(api);
      else reject(new Error("friendlyChallenge API nach dem Laden nicht verfuegbar")); // i18n-ok: nur Konsolen-Log, nie in der UI
    };
    const onError = () => {
      // Fehlgeschlagenes Skript-Tag entfernen, sonst wartet ein spaeterer Versuch ewig auf
      // ein `load`, das fuer dieses Element nie mehr kommt.
      script?.remove();
      reject(new Error("FriendlyCaptcha-Skript konnte nicht geladen werden")); // i18n-ok: nur Konsolen-Log, nie in der UI
    };
    if (!script) {
      script = doc.createElement("script");
      script.id = FRIENDLY_CAPTCHA_SCRIPT_ID;
      script.src = FRIENDLY_CAPTCHA_SCRIPT_SRC;
      script.type = "module";
      script.async = true;
      script.addEventListener("load", onLoad, { once: true });
      script.addEventListener("error", onError, { once: true });
      doc.body.appendChild(script);
    } else {
      // Skript-Tag existiert schon, ist aber noch nicht fertig ausgefuehrt (API fehlt noch).
      script.addEventListener("load", onLoad, { once: true });
      script.addEventListener("error", onError, { once: true });
    }
  }).catch((error: unknown) => {
    loadPromise = null;
    throw error;
  });
  return loadPromise;
}

// Nur fuer Tests: Lade-Cache zuruecksetzen.
export function resetFriendlyChallengeLoaderForTests() {
  loadPromise = null;
}

type MountOptions = {
  sitekey: string;
  language: string;
  onSolved: (solution: string) => void;
  onError?: (error: unknown) => void;
};

// Erzeugt im (von React verwalteten) Container ein eigenes Kind-Element und haengt das Widget
// daran. Das Kind wird nicht von React gerendert, weil `destroy()` sein Element selbst aus dem DOM
// entfernt - so kollidiert das nie mit Reacts eigener DOM-Verwaltung. Rueckgabe: Aufraeumfunktion.
export function mountFriendlyCaptcha(container: HTMLElement, api: FriendlyChallengeApi, options: MountOptions): () => void {
  const doc = container.ownerDocument;
  const host = doc.createElement("div");
  host.className = "frc-captcha";
  host.dataset.attached = "1";
  host.dataset.sitekey = options.sitekey;
  host.dataset.lang = options.language;
  host.dataset.start = "auto";
  host.dataset.puzzleEndpoint = FRIENDLY_CAPTCHA_PUZZLE_ENDPOINT;
  container.appendChild(host);

  let widget: FriendlyCaptchaWidget | null = null;
  try {
    widget = new api.WidgetInstance(host, {
      sitekey: options.sitekey,
      language: options.language,
      startMode: "auto",
      puzzleEndpoint: FRIENDLY_CAPTCHA_PUZZLE_ENDPOINT,
      doneCallback: (solution) => options.onSolved(solution),
      errorCallback: (error) => options.onError?.(error),
    });
  } catch (error) {
    host.remove();
    throw error;
  }

  return () => {
    widget?.destroy();
    widget = null;
    // destroy() entfernt das Element bereits; falls die Bibliothek das kuenftig nicht mehr tut,
    // trotzdem sicher aus dem Container nehmen.
    if (host.parentNode) host.remove();
  };
}
