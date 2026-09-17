"use client";

import { useState } from "react";

import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { browserSupportsPasskeys, createPasskeyCredential } from "@/lib/webauthn";
import { PasskeyRegistrationStart, TotpEnrollmentStart, UserMfaOverview } from "@/types/api";

export function formatMfaDate(value: string | null) {
  if (!value) return "Noch nie";
  return new Intl.DateTimeFormat("de-CH", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function mfaFactorTypeLabel(type: "totp" | "webauthn") {
  return type === "totp" ? "TOTP" : "Passkey";
}

/** Shared TOTP/passkey enrollment + factor-deletion state machine behind both MFA
 * surfaces in this app - admin-mfa-settings.tsx (platform admins) and mfa-profile-
 * panel.tsx (tenant users) - parameterized by basePath ("/api/admin/mfa" vs.
 * "/api/users/me/mfa"), since the two REST namespaces are otherwise identical shape.
 *
 * Audit fix, 2026-09-17: this used to be two independently hand-maintained copies of the
 * same start/complete-TOTP, start/complete-passkey, delete-factor flow - including two
 * byte-for-byte identical helper functions (formatDate/factorTypeLabel, now
 * formatMfaDate/mfaFactorTypeLabel above). This is security-relevant code; a safety check
 * added to one copy could easily be forgotten on the other.
 *
 * Callers own their own overview loading strategy (the admin page gets it server-rendered
 * up front, the profile panel fetches it on open) by passing the current value in and
 * getting told what to set it to next, rather than the hook owning that too - the two
 * pages' loading strategies genuinely differ and shouldn't be forced into one shape. Both
 * callers already shared one `busy` flag across every action (not split per action-type),
 * matching the profile panel's original, more conservative behavior (prevents overlapping
 * TOTP/passkey mutations) - the admin page previously had two independent flags
 * (busyTotp/busyPasskey), unified here as part of removing the duplication. */
export function useMfaEnrollment(
  basePath: string,
  overview: UserMfaOverview | null,
  setOverview: (next: UserMfaOverview) => void
) {
  const showToast = useToast();
  const confirm = useConfirm();
  const [totpSetup, setTotpSetup] = useState<TotpEnrollmentStart | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [totpLabel, setTotpLabel] = useState("");
  const [passkeyLabel, setPasskeyLabel] = useState("");
  const [busy, setBusy] = useState(false);

  async function startTotp() {
    setBusy(true);
    try {
      const result = await browserApiFetch<TotpEnrollmentStart>(`${basePath}/totp/start`, { method: "POST" });
      setTotpSetup(result);
      setTotpCode("");
      setTotpLabel("");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "TOTP-Setup konnte nicht gestartet werden", "error");
    } finally {
      setBusy(false);
    }
  }

  async function completeTotp() {
    if (!totpSetup) return;
    setBusy(true);
    try {
      const next = await browserApiFetch<UserMfaOverview>(`${basePath}/totp/complete`, {
        method: "POST",
        body: JSON.stringify({
          flow_token: totpSetup.flow_token,
          code: totpCode,
          label: totpLabel || null,
        }),
      });
      setOverview(next);
      setTotpSetup(null);
      setTotpCode("");
      setTotpLabel("");
      showToast("TOTP erfolgreich eingerichtet", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "TOTP konnte nicht bestätigt werden", "error");
    } finally {
      setBusy(false);
    }
  }

  async function startPasskey() {
    if (!browserSupportsPasskeys()) {
      showToast("Dieser Browser unterstützt keine Passkeys.", "error");
      return;
    }
    setBusy(true);
    try {
      const start = await browserApiFetch<PasskeyRegistrationStart>(`${basePath}/passkeys/start`, { method: "POST" });
      const credential = await createPasskeyCredential(start.public_key);
      const next = await browserApiFetch<UserMfaOverview>(`${basePath}/passkeys/complete`, {
        method: "POST",
        body: JSON.stringify({
          flow_token: start.flow_token,
          label: passkeyLabel || null,
          credential,
        }),
      });
      setOverview(next);
      setPasskeyLabel("");
      showToast("Passkey erfolgreich eingerichtet", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Passkey konnte nicht eingerichtet werden", "error");
    } finally {
      setBusy(false);
    }
  }

  async function deleteFactor(factorId: string, label: string) {
    const ok = await confirm({
      message: `MFA-Faktor "${label}" wirklich entfernen?`,
      tone: "danger",
      confirmLabel: "Entfernen",
    });
    if (!ok) return;
    try {
      const next = await browserApiFetch<UserMfaOverview>(`${basePath}/factors/${factorId}`, {
        method: "DELETE",
      });
      setOverview(next);
      showToast("MFA-Faktor entfernt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "MFA-Faktor konnte nicht entfernt werden", "error");
    }
  }

  const hasTotpFactor = overview?.factors.some((factor) => factor.factor_type === "totp") ?? false;
  const hasPasskeyFactor = overview?.factors.some((factor) => factor.factor_type === "webauthn") ?? false;

  return {
    totpSetup,
    setTotpSetup,
    totpCode,
    setTotpCode,
    totpLabel,
    setTotpLabel,
    passkeyLabel,
    setPasskeyLabel,
    busy,
    // Exposed (not just used internally) so a caller with its own extra mutating action -
    // mfa-profile-panel.tsx's setPreferredMethod, which has no equivalent on the admin
    // side - can fold into the same shared busy flag instead of needing a second one.
    setBusy,
    startTotp,
    completeTotp,
    startPasskey,
    deleteFactor,
    hasTotpFactor,
    hasPasskeyFactor,
  };
}
