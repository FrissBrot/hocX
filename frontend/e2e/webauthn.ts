import type { Page } from "@playwright/test";

/** Registers a Chromium CDP virtual authenticator on `page` so `navigator.credentials.create()`/
 * `.get()` calls made by the page (see lib/webauthn.ts's createPasskeyCredential/
 * getPasskeyAssertion) resolve against a real, software-backed authenticator instead of hanging
 * forever waiting for a physical one - Chromium intercepts the WebAuthn API for any page whose
 * CDP session has this domain enabled and routes it to the virtual authenticator instead.
 *
 * ctap2 + resident keys + user verification: matches a modern platform authenticator (Face ID/
 * Touch ID/Windows Hello), the same class of device admin-mfa-settings.tsx's "Passkey" option
 * is written for - `isUserVerified: true` means every ceremony succeeds without any prompt,
 * which is exactly what a headless/CI browser needs.
 *
 * Returns a cleanup function that removes the authenticator; call it once the test is done with
 * passkey ceremonies on this page (not strictly required - closing the page/context tears the
 * CDP session down anyway - but keeps a long-lived page's virtual authenticator list from
 * growing across multiple enrolments within the same test). */
export async function addVirtualAuthenticator(page: Page): Promise<() => Promise<void>> {
  const client = await page.context().newCDPSession(page);
  await client.send("WebAuthn.enable");
  const { authenticatorId } = await client.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2",
      transport: "internal",
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
    },
  });
  return async () => {
    await client.send("WebAuthn.removeVirtualAuthenticator", { authenticatorId });
  };
}
