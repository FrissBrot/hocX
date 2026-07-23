const COOLDOWN_MS = 15_000;
const STORAGE_KEY = "hocx-bridge-last-attempt";

/**
 * Navigates to a tenant's custom-domain bridge URL, but only if we haven't just tried this in
 * the last COOLDOWN_MS. Without this, a stale-but-still-valid main-domain session combined with
 * any downstream hiccup that bounces the browser back here (e.g. the fresh custom-domain cookie
 * not yet being recognised) turns "auto-redirect to your domain" into an infinite redirect loop
 * that never lets the user actually reach the app. Worst case with the guard: one redundant
 * bounce, then the app renders normally on the main domain.
 */
export function attemptBridgeRedirect(bridgeUrl: string): boolean {
  const last = Number(window.sessionStorage.getItem(STORAGE_KEY) ?? 0);
  const now = Date.now();
  if (now - last < COOLDOWN_MS) {
    return false;
  }
  window.sessionStorage.setItem(STORAGE_KEY, String(now));
  window.location.href = bridgeUrl;
  return true;
}
